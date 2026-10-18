"""
Tank stock: saving the daily stock sheet (with every tank's dip reading) and
recording fuel receipts. There is no approval step: a saved sheet is final,
and only the latest sheet at an outlet can be edited or deleted. Rules are
checked on the server and every change is written to the audit log.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from audit.models import AuditLog
from sales.models import DailySalesLine
from sales.services import viewable_outlets
from station.models import Tank

from .models import StockLine, StockSheet, TankReceipt

ZERO = Decimal("0")


def stock_sheets_for(user):
    return StockSheet.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


def receipts_for(user):
    return TankReceipt.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


def can_work_at(user, outlet):
    return user.accessible_outlets().filter(pk=outlet.pk).exists()


def is_latest(sheet):
    return not StockSheet.objects.filter(outlet=sheet.outlet, business_date__gt=sheet.business_date).exists()


def can_change(sheet, user):
    return can_work_at(user, sheet.outlet) and is_latest(sheet)


def stock_locked(outlet, day):
    """Once a day's stock is saved, its receipts and shift cards may no longer change silently."""
    return StockSheet.objects.filter(outlet=outlet, business_date=day).exists()


# --- Where the numbers come from --------------------------------------------


def sales_lines_for_tank(tank, day):
    """
    Shift Card lines whose fuel came from `tank` on `day`. Lines recorded
    before tanks were set up use the nozzle's current tank.
    """
    return DailySalesLine.objects.filter(
        sheet__outlet=tank.outlet, sheet__business_date=day, closing_reading__isnull=False,
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
    """Reasons the outlet's stock for `day` cannot be saved yet."""
    unlinked = (
        DailySalesLine.objects.filter(sheet__outlet=outlet, sheet__business_date=day, tank__isnull=True,
                                      nozzle__tank__isnull=True, total_delivery__gt=0)
        .values_list("nozzle__code", flat=True).distinct()
    )
    if unlinked:
        return [f"Nozzle {', '.join(sorted(unlinked))} dispensed fuel but is not linked to a tank. "
                "The Dealer links nozzles to tanks on the outlet's set-up page."]
    return []


def stale_tanks(sheet):
    """Tanks whose receipts or shift cards changed after this sheet was saved."""
    changed = []
    for line in sheet.lines.select_related("tank"):
        live = movements(line.tank, sheet.business_date)
        if (live["fuel_received"], live["total_delivery"]) != (line.fuel_received, line.total_delivery):
            changed.append(line.tank.code)
    return changed


def tank_rows(outlet, day, sheet=None):
    """
    One row per tank for the stock sheet form: opening stock (previous measured
    closing, or the tank's starting stock), today's movements and the
    calculated closing.
    """
    if sheet is not None:
        tanks = [line.tank for line in sheet.lines.select_related("tank__product")]
        openings = {line.tank_id: line.opening_stock for line in sheet.lines.all()}
    else:
        tanks = list(Tank.objects.filter(outlet=outlet, is_active=True).select_related("product"))
        openings = {}
    rows = []
    for tank in tanks:
        if tank.pk not in openings:
            previous = (StockLine.objects.filter(tank=tank, sheet__business_date__lt=day)
                        .order_by("-sheet__business_date").first())
            openings[tank.pk] = previous.measured_closing if previous else tank.starting_stock
        moved = movements(tank, day)
        rows.append({"tank": tank, "opening": openings[tank.pk], **moved,
                     "calculated": openings[tank.pk] + moved["fuel_received"] - moved["total_delivery"]})
    return rows


# --- Saving the stock sheet --------------------------------------------------------


@transaction.atomic
def save_stock_sheet(*, user, outlet=None, business_date=None, entries, notes="", sheet=None, request=None):
    """
    Create (sheet=None) or update a stock sheet. `entries` maps tank id to
    (measured_closing, notes) and must cover every tank on the sheet.
    """
    is_new = sheet is None
    if is_new:
        if not can_work_at(user, outlet):
            raise PermissionDenied("You are not assigned to this outlet.")
        if business_date > timezone.localdate():
            raise ValidationError("Stock cannot be recorded for a future date.")
        latest = StockSheet.objects.select_for_update().filter(outlet=outlet).order_by("-business_date").first()
        if latest is not None and business_date <= latest.business_date:
            raise ValidationError(f"Stock sheets are entered in date order. The latest one at {outlet.code} is for "
                                  f"{latest.business_date:%d %b %Y}.")
    else:
        sheet = StockSheet.objects.select_for_update().select_related("outlet").get(pk=sheet.pk)
        outlet, business_date = sheet.outlet, sheet.business_date
        if not can_work_at(user, outlet):
            raise PermissionDenied("You are not assigned to this outlet.")
        if not is_latest(sheet):
            raise ValidationError("A later stock sheet already starts from this measured stock, so it cannot be changed.")

    problems = day_problems(outlet, business_date)
    if problems:
        raise ValidationError(problems)
    rows = tank_rows(outlet, business_date, sheet)
    if not rows:
        raise ValidationError("This outlet has no active tanks yet. The Dealer adds them on the outlet's set-up page.")
    if {row["tank"].pk for row in rows} != set(entries):
        raise ValidationError("The tank rows do not match this outlet. Reload the page and try again.")

    if is_new:
        sheet = StockSheet.objects.create(business=user.business, outlet=outlet, business_date=business_date,
                                          notes=notes, entered_by=user)
        before = {}
    else:
        before = {line.tank.code: str(line.measured_closing) for line in sheet.lines.select_related("tank")}
        sheet.notes, sheet.updated_by = notes, user
        sheet.save()
        sheet.lines.all().delete()

    for row in rows:
        measured, line_notes = entries[row["tank"].pk]
        line = StockLine(business=sheet.business, sheet=sheet, tank=row["tank"], product=row["tank"].product,
                         opening_stock=row["opening"], fuel_received=row["fuel_received"],
                         total_delivery=row["total_delivery"], testing_litres=row["testing_litres"],
                         measured_closing=measured, notes=line_notes or "")
        line.calculated_closing = row["calculated"]
        try:
            line.full_clean()
        except ValidationError as error:
            raise ValidationError(f"Tank {row['tank'].code}: {'; '.join(error.messages)}")
        line.save()

    flagged = [line.tank.code for line in sheet.lines.select_related("tank") if line.is_flagged]
    measured = {line.tank.code: str(line.measured_closing) for line in sheet.lines.select_related("tank")}
    AuditLog.record(AuditLog.Action.CREATE if is_new else AuditLog.Action.UPDATE,
                    f"{'Saved' if is_new else 'Edited'} {sheet}", user=user, obj=sheet, request=request,
                    changes={"measured": measured if is_new else {"from": before, "to": measured},
                             **({"flagged_tanks": flagged} if flagged else {})})
    return sheet


@transaction.atomic
def delete_stock_sheet(sheet, *, user, request=None):
    sheet = StockSheet.objects.select_for_update().get(pk=sheet.pk)
    if not can_work_at(user, sheet.outlet):
        raise PermissionDenied("You are not assigned to this outlet.")
    if not is_latest(sheet):
        raise ValidationError("Only the latest stock sheet at an outlet can be deleted.")
    AuditLog.record(AuditLog.Action.DELETE, f"Deleted {sheet}", user=user, obj=sheet, request=request,
                    changes={line.tank.code: str(line.measured_closing) for line in sheet.lines.select_related("tank")})
    sheet.delete()


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
            f"Stock for {tank.outlet.code} on {day:%d %b %Y} is already saved, so its receipts are locked."
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
