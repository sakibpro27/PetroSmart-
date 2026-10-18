"""
Tank stock workflow: creating, refreshing, submitting and approving stock
sheets, and recording fuel receipts. Rules are checked on the server and every
change is written to the audit log.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from audit.models import AuditLog
from sales.models import DailySalesLine, DailySalesSheet
from sales.services import viewable_outlets
from station.models import Tank

from .models import StockLine, StockSheet, TankReceipt

Status = StockSheet.Status
COUNTED_SALES = (DailySalesSheet.Status.SUBMITTED, DailySalesSheet.Status.APPROVED)
ZERO = Decimal("0")


def stock_sheets_for(user):
    return StockSheet.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


def receipts_for(user):
    return TankReceipt.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


def can_work_at(user, outlet):
    return user.accessible_outlets().filter(pk=outlet.pk).exists()


def can_edit(sheet, user):
    return sheet.status == Status.DRAFT and can_work_at(user, sheet.outlet)


def _require_dealer(user):
    if not user.is_dealer:
        raise PermissionDenied("Only the Dealer can do this.")


# --- Where the numbers come from --------------------------------------------


def sales_lines_for_tank(tank, day):
    """
    Daily Sales lines whose fuel came from `tank` on `day`. Only submitted or
    approved sheets count. Lines recorded before tanks were set up use the
    nozzle's current tank.
    """
    return DailySalesLine.objects.filter(
        sheet__outlet=tank.outlet, sheet__business_date=day, sheet__status__in=COUNTED_SALES,
        closing_reading__isnull=False,
    ).filter(Q(tank=tank) | Q(tank__isnull=True, nozzle__tank=tank))


def movements(tank, day):
    """Fuel received into and delivered out of a tank on one day."""
    receipts = TankReceipt.objects.filter(tank=tank, received_on=day)
    if receipts.exclude(volume_basis=tank.volume_basis).exists():
        raise ValidationError(
            f"Tank {tank.code} has receipts measured on a different volume basis. "
            "Temperature-corrected and observed litres cannot be mixed."
        )
    delivered = sales_lines_for_tank(tank, day).aggregate(delivery=Sum("total_delivery"), testing=Sum("testing_litres"))
    return {
        "fuel_received": receipts.aggregate(total=Sum("litres"))["total"] or ZERO,
        "total_delivery": delivered["delivery"] or ZERO,
        "testing_litres": delivered["testing"] or ZERO,
    }


def day_problems(outlet, day):
    """Reasons the outlet's stock for `day` cannot be finalised yet."""
    problems = []
    drafts = DailySalesSheet.objects.filter(outlet=outlet, business_date=day, status=DailySalesSheet.Status.DRAFT)
    if drafts.exists():
        names = ", ".join(sheet.shift.name for sheet in drafts.select_related("shift"))
        problems.append(f"Daily Sales for the {names} shift are still in Draft. Submit them first.")
    unlinked = (
        DailySalesLine.objects.filter(sheet__outlet=outlet, sheet__business_date=day, sheet__status__in=COUNTED_SALES,
                                      tank__isnull=True, nozzle__tank__isnull=True, total_delivery__gt=0)
        .values_list("nozzle__code", flat=True).distinct()
    )
    if unlinked:
        problems.append(
            f"Nozzle {', '.join(sorted(unlinked))} dispensed fuel but is not linked to a tank. "
            "The Dealer links nozzles to tanks on the outlet's set-up page."
        )
    return problems


def stale_tanks(sheet):
    """Tanks whose receipts or Daily Sales changed after this sheet was submitted."""
    changed = []
    for line in sheet.lines.select_related("tank"):
        live = movements(line.tank, sheet.business_date)
        if (live["fuel_received"], live["total_delivery"]) != (line.fuel_received, line.total_delivery):
            changed.append(line.tank.code)
    return changed


def stock_locked(outlet, day):
    """Once a day's stock is submitted, its receipts and Daily Sales may no longer change silently."""
    return StockSheet.objects.filter(outlet=outlet, business_date=day).exclude(status=Status.DRAFT).exists()


# --- Stock sheets -------------------------------------------------------------


@transaction.atomic
def create_stock_sheet(*, user, outlet, business_date, request=None):
    if not can_work_at(user, outlet):
        raise PermissionDenied("You are not assigned to this outlet.")
    if business_date > timezone.localdate():
        raise ValidationError("Stock cannot be recorded for a future date.")
    latest = (StockSheet.objects.select_for_update().filter(outlet=outlet).order_by("-business_date").first())
    if latest is not None:
        if business_date <= latest.business_date:
            raise ValidationError(
                f"Stock sheets are entered in date order. The latest one at {outlet.code} is for "
                f"{latest.business_date:%d %b %Y}."
            )
        if latest.status == Status.DRAFT:
            raise ValidationError(f"Finish and submit the stock sheet for {latest.business_date:%d %b %Y} first.")
    tanks = list(Tank.objects.for_business(user.business).filter(outlet=outlet, is_active=True).select_related("product"))
    if not tanks:
        raise ValidationError("This outlet has no active tanks yet. The Dealer adds them on the outlet's set-up page.")

    sheet = StockSheet.objects.create(business=user.business, outlet=outlet, business_date=business_date, entered_by=user)
    for tank in tanks:
        previous = (
            StockLine.objects.filter(tank=tank, sheet__business_date__lt=business_date)
            .order_by("-sheet__business_date").first()
        )
        StockLine.objects.create(
            business=user.business, sheet=sheet, tank=tank, product=tank.product,
            opening_stock=previous.measured_closing if previous else tank.starting_stock,
            **movements(tank, business_date),
        )
    AuditLog.record(AuditLog.Action.CREATE, f"Started {sheet}", user=user, obj=sheet, request=request)
    return sheet


def refresh_draft(sheet):
    """Pull the latest receipts and Daily Sales figures into a Draft sheet."""
    if sheet.status != Status.DRAFT:
        return
    for line in sheet.lines.select_related("tank"):
        for field, value in movements(line.tank, sheet.business_date).items():
            setattr(line, field, value)
        line.save()


@transaction.atomic
def save_draft(sheet, formset, notes_form, *, user, request=None):
    sheet = StockSheet.objects.select_for_update().get(pk=sheet.pk)
    if not can_edit(sheet, user):
        raise ValidationError("This stock sheet can no longer be edited.")
    line_ids = set(sheet.lines.values_list("pk", flat=True))
    if any(form.instance.pk not in line_ids for form in formset.forms):
        raise ValidationError("These readings do not match this sheet. Reload the page and try again.")
    changes = {
        form.instance.tank.code: {name: {"from": _plain(form.initial.get(name)), "to": _plain(form.cleaned_data.get(name))}
                                  for name in form.changed_data}
        for form in formset.forms if form.has_changed()
    }
    formset.save()
    if notes_form.has_changed():
        changes["sheet notes"] = notes_form.cleaned_data["notes"]
        notes_form.save()
    refresh_draft(sheet)
    if changes:
        AuditLog.record(AuditLog.Action.UPDATE, f"Updated dip readings on {sheet}", user=user, obj=sheet,
                        changes=changes, request=request)
    return sheet


def _plain(value):
    return value if value is None or isinstance(value, bool) else str(value)


@transaction.atomic
def submit_stock_sheet(sheet, *, user, request=None):
    sheet = StockSheet.objects.select_for_update().get(pk=sheet.pk)
    if not can_edit(sheet, user):
        raise ValidationError("Only a Draft stock sheet at your outlet can be submitted.")
    problems = day_problems(sheet.outlet, sheet.business_date)
    if problems:
        raise ValidationError(problems)
    refresh_draft(sheet)
    lines = list(sheet.lines.select_related("tank"))
    missing = [line.tank.code for line in lines if line.measured_closing is None]
    if missing:
        raise ValidationError(f"Enter the measured (dip) closing stock for tank {', '.join(missing)}.")
    for line in lines:
        try:
            line.full_clean()
        except ValidationError as error:
            raise ValidationError(f"Tank {line.tank.code}: {'; '.join(error.messages)}")
    sheet.status = Status.SUBMITTED
    sheet.submitted_by, sheet.submitted_at = user, timezone.now()
    sheet.save()
    flagged = [line.tank.code for line in lines if line.is_flagged]
    AuditLog.record(AuditLog.Action.SUBMIT, f"Submitted {sheet} for approval", user=user, obj=sheet,
                    changes={"flagged_tanks": flagged} if flagged else {}, request=request)
    return sheet


@transaction.atomic
def approve_stock_sheet(sheet, *, user, request=None):
    _require_dealer(user)
    sheet = StockSheet.objects.select_for_update().get(pk=sheet.pk)
    if sheet.status != Status.SUBMITTED:
        raise ValidationError("Only a stock sheet awaiting approval can be approved.")
    sheet.status = Status.APPROVED
    sheet.approved_by, sheet.approved_at = user, timezone.now()
    sheet.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    AuditLog.record(AuditLog.Action.APPROVE, f"Approved {sheet}", user=user, obj=sheet, request=request)
    return sheet


@transaction.atomic
def return_stock_sheet(sheet, *, user, note, request=None):
    _require_dealer(user)
    sheet = StockSheet.objects.select_for_update().get(pk=sheet.pk)
    if sheet.status != Status.SUBMITTED:
        raise ValidationError("Only a stock sheet awaiting approval can be sent back.")
    if not note.strip():
        raise ValidationError("Write a note telling the manager what to check.")
    if not sheet.is_latest:
        raise ValidationError("A later stock sheet already starts from this measured stock, so it cannot be sent back.")
    sheet.status = Status.DRAFT
    sheet.review_note = note.strip()
    sheet.submitted_by = sheet.submitted_at = None
    sheet.save()
    AuditLog.record(AuditLog.Action.REJECT, f"Sent back {sheet}", user=user, obj=sheet,
                    changes={"note": sheet.review_note}, request=request)
    return sheet


# --- Fuel receipts ------------------------------------------------------------


def _check_not_from_invoice(receipt):
    if receipt.purchase_id:
        raise ValidationError(
            f"This receipt is part of invoice {receipt.purchase.invoice_number}. Change it from the fuel purchase instead."
        )


def _check_receipt_allowed(user, tank, day):
    if not can_work_at(user, tank.outlet):
        raise PermissionDenied("You are not assigned to this outlet.")
    if day > timezone.localdate():
        raise ValidationError("A receipt cannot be dated in the future.")
    if stock_locked(tank.outlet, day):
        raise ValidationError(
            f"Stock for {tank.outlet.code} on {day:%d %b %Y} is already submitted, so its receipts are locked."
        )


@transaction.atomic
def save_receipt(form, *, user, request=None):
    """Create or update a receipt from a valid ReceiptForm."""
    receipt = form.instance
    is_new = receipt.pk is None
    if not is_new:
        original = TankReceipt.objects.select_related("tank__outlet", "purchase").get(pk=receipt.pk)
        _check_not_from_invoice(original)
        _check_receipt_allowed(user, original.tank, original.received_on)
    _check_receipt_allowed(user, form.cleaned_data["tank"], form.cleaned_data["received_on"])
    receipt = form.save(commit=False)
    receipt.outlet = receipt.tank.outlet
    if is_new:
        receipt.entered_by = user
    receipt.save()
    AuditLog.record(AuditLog.Action.CREATE if is_new else AuditLog.Action.UPDATE,
                    f"{'Recorded' if is_new else 'Updated'} receipt {receipt}", user=user, obj=receipt,
                    changes=form.audit_changes(), request=request)
    return receipt


@transaction.atomic
def delete_receipt(receipt, *, user, request=None):
    _check_not_from_invoice(receipt)
    _check_receipt_allowed(user, receipt.tank, receipt.received_on)
    description = f"Deleted receipt {receipt} (ref. {receipt.reference or '—'})"
    AuditLog.record(AuditLog.Action.DELETE, description, user=user, obj=receipt,
                    changes={"litres": str(receipt.litres), "tank": receipt.tank.code,
                             "received_on": str(receipt.received_on), "reference": receipt.reference},
                    request=request)
    receipt.delete()
