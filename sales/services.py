"""
Daily Sales workflow. Every change of status happens in this module, inside a
database transaction, with the permission and order rules checked on the
server and an audit-log entry written.

Rules that keep the reading history consistent:

1. Sheets at an outlet are created in (date, shift order) sequence, and the
   previous sheet must be submitted before the next one is started.
2. A sheet's opening readings are copied from the previous closing readings
   (or from the nozzle's starting reading) and cannot be typed over.
3. Only the latest sheet at an outlet may be sent back to Draft. Older sheets
   are fixed through a correction, which also updates the next shift's
   opening reading and records both changes.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from station.models import FuelPrice, Nozzle
from tenants.models import Outlet

from .calculations import calculate_line
from .models import CorrectionLine, DailySalesLine, DailySalesSheet, SalesCorrection

Status = DailySalesSheet.Status


# --- Who may see what -------------------------------------------------------


def viewable_outlets(user):
    """Dealers see every outlet (inactive ones too, for history); managers their assigned ones."""
    if user.is_dealer:
        return Outlet.objects.for_business(user.business)
    return user.accessible_outlets()


def sheets_for(user):
    return DailySalesSheet.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


def can_edit(sheet, user):
    return sheet.status == Status.DRAFT and user.accessible_outlets().filter(pk=sheet.outlet_id).exists()


def _require_dealer(user):
    if not user.is_dealer:
        raise PermissionDenied("Only the Dealer can do this.")


def _lock(sheet):
    """Re-read the sheet with a row lock so two people cannot change it at once."""
    return DailySalesSheet.objects.select_for_update().get(pk=sheet.pk)


def _stock_locked(outlet, day):
    from stock.services import stock_locked  # imported here: the stock app builds on sales

    return stock_locked(outlet, day)


def _sheet_label(sheet):
    return f"{sheet.business_date:%d %b %Y}, {sheet.shift.name} shift"


# --- Reading history --------------------------------------------------------


def previous_line(nozzle, sheet):
    """The same nozzle's line on the closest earlier sheet, or None."""
    earlier = DailySalesLine.objects.filter(nozzle=nozzle).exclude(sheet__in=sheet.later_sheets()).exclude(sheet=sheet)
    return earlier.order_by("-sheet__business_date", "-sheet__shift_sort_order").first()


def next_line(line):
    """The same nozzle's line on the closest later sheet, or None."""
    return (
        DailySalesLine.objects.filter(nozzle=line.nozzle)
        .filter(line.sheet._later_q("sheet__"))
        .order_by("sheet__business_date", "sheet__shift_sort_order")
        .first()
    )


# --- Creating and entering a sheet -----------------------------------------


@transaction.atomic
def create_sheet(*, user, shift, business_date, request=None):
    outlet = shift.outlet
    if not user.accessible_outlets().filter(pk=outlet.pk).exists():
        raise PermissionDenied("You are not assigned to this outlet.")
    if business_date > timezone.localdate():
        raise ValidationError("Daily Sales cannot be recorded for a future date.")
    if _stock_locked(outlet, business_date):
        raise ValidationError(
            f"Tank stock for {outlet.code} on {business_date:%d %b %Y} is already submitted. "
            "The Dealer must send that stock sheet back before more sales are added for this date."
        )

    latest = (
        DailySalesSheet.objects.select_for_update()
        .filter(outlet=outlet)
        .order_by("-business_date", "-shift_sort_order")
        .first()
    )
    if latest is not None:
        if (business_date, shift.sort_order) <= (latest.business_date, latest.shift_sort_order):
            raise ValidationError(
                f"Sheets are entered in order. The latest sheet at {outlet.code} is for "
                f"{_sheet_label(latest)}. Choose a later date or shift."
            )
        if latest.status == Status.DRAFT:
            raise ValidationError(f"Finish and submit the {_sheet_label(latest)} sheet first.")

    nozzles = list(
        Nozzle.objects.for_business(user.business).filter(outlet=outlet, is_active=True).select_related("product")
    )
    if not nozzles:
        raise ValidationError("This outlet has no active nozzles yet. The Dealer sets them up under Outlets.")

    prices, missing = {}, []
    for product in {n.product for n in nozzles}:
        price = FuelPrice.price_on(outlet, product, business_date)
        if price is None:
            missing.append(product.name)
        else:
            prices[product.pk] = price.price_per_litre
    if missing:
        raise ValidationError(
            f"No selling price is set at {outlet.code} for {', '.join(sorted(missing))} "
            f"on {business_date:%d %b %Y}. The Dealer sets prices on the outlet's set-up page."
        )

    sheet = DailySalesSheet.objects.create(
        business=user.business, outlet=outlet, shift=shift, business_date=business_date,
        shift_sort_order=shift.sort_order, entered_by=user,
    )
    for nozzle in nozzles:
        before = previous_line(nozzle, sheet)
        DailySalesLine.objects.create(
            business=user.business, sheet=sheet, nozzle=nozzle, product=nozzle.product, tank=nozzle.tank,
            opening_reading=before.closing_reading if before else nozzle.initial_reading,
            price_per_litre=prices[nozzle.product_id],
        )
    AuditLog.record(AuditLog.Action.CREATE, f"Started Daily Sales {sheet}", user=user, obj=sheet, request=request)
    return sheet


@transaction.atomic
def save_draft(sheet, formset, notes_form, *, user, request=None):
    """Save entered readings on a Draft sheet (validated forms only)."""
    sheet = _lock(sheet)
    if not can_edit(sheet, user):
        raise ValidationError("This sheet can no longer be edited.")
    # Every posted row must be one of this sheet's own lines (protects against forged row ids).
    line_ids = set(sheet.lines.values_list("pk", flat=True))
    if any(form.instance.pk not in line_ids for form in formset.forms):
        raise ValidationError("These readings do not match this sheet. Reload the page and try again.")
    changes = {}
    for form in formset.forms:
        if form.has_changed():
            changes[form.instance.nozzle.code] = {
                name: {"from": _plain(form.initial.get(name)), "to": _plain(form.cleaned_data.get(name))}
                for name in form.changed_data
            }
    formset.save()
    if notes_form.has_changed():
        changes["sheet notes"] = notes_form.cleaned_data["notes"]
        notes_form.save()
    if changes:
        AuditLog.record(AuditLog.Action.UPDATE, f"Updated readings on {sheet}", user=user, obj=sheet,
                        changes=changes, request=request)
    return sheet


def _plain(value):
    return value if value is None or isinstance(value, bool) else str(value)


@transaction.atomic
def submit_sheet(sheet, *, user, request=None):
    sheet = _lock(sheet)
    if not can_edit(sheet, user):
        raise ValidationError("Only a Draft sheet at your outlet can be submitted.")
    lines = list(sheet.lines.select_related("nozzle"))
    missing = [line.nozzle.code for line in lines if line.closing_reading is None]
    if missing:
        raise ValidationError(f"Enter the closing reading for nozzle {', '.join(missing)} before submitting.")
    for line in lines:
        try:
            line.full_clean()
        except ValidationError as error:
            raise ValidationError(f"Nozzle {line.nozzle.code}: {'; '.join(error.messages)}")
        if line.tank_id != line.nozzle.tank_id:
            # Record which tank the fuel came from (the nozzle may have been linked since the sheet started).
            line.tank_id = line.nozzle.tank_id
            line.save(update_fields=["tank"])
    sheet.status = Status.SUBMITTED
    sheet.submitted_by, sheet.submitted_at = user, timezone.now()
    sheet.save()
    AuditLog.record(AuditLog.Action.SUBMIT, f"Submitted Daily Sales {sheet} for approval", user=user,
                    obj=sheet, request=request)
    return sheet


# --- Dealer review ----------------------------------------------------------


@transaction.atomic
def approve_sheet(sheet, *, user, request=None):
    _require_dealer(user)
    sheet = _lock(sheet)
    if sheet.status != Status.SUBMITTED:
        raise ValidationError("Only a sheet awaiting approval can be approved.")
    # Approval changes the status only. Readings and figures stay exactly as entered.
    sheet.status = Status.APPROVED
    sheet.approved_by, sheet.approved_at = user, timezone.now()
    sheet.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    AuditLog.record(AuditLog.Action.APPROVE, f"Approved Daily Sales {sheet}", user=user, obj=sheet, request=request)
    return sheet


@transaction.atomic
def return_sheet(sheet, *, user, note, request=None):
    _require_dealer(user)
    sheet = _lock(sheet)
    if sheet.status != Status.SUBMITTED:
        raise ValidationError("Only a sheet awaiting approval can be sent back.")
    if not note.strip():
        raise ValidationError("Write a note telling the manager what to fix.")
    if not sheet.is_latest:
        raise ValidationError(
            "A later sheet already starts from these closing readings. "
            "Approve this sheet, then request a correction instead."
        )
    if _stock_locked(sheet.outlet, sheet.business_date):
        raise ValidationError(
            "Tank stock for this date is already submitted from these figures. "
            "Approve this sheet, then request a correction instead."
        )
    sheet.status = Status.DRAFT
    sheet.review_note = note.strip()
    sheet.submitted_by = sheet.submitted_at = None
    sheet.save()
    AuditLog.record(AuditLog.Action.REJECT, f"Sent back Daily Sales {sheet}", user=user, obj=sheet,
                    changes={"note": sheet.review_note}, request=request)
    return sheet


# --- Corrections to approved sheets ----------------------------------------


def _check_change(line, closing, testing, price):
    """Validate one proposed change, including its effect on the next shift."""
    try:
        calculate_line(line.opening_reading, closing, testing, price, meter_reset=line.meter_reset,
                       before_reset=line.reading_before_reset, after_reset=line.reading_after_reset)
    except ValidationError as error:
        raise ValidationError(f"Nozzle {line.nozzle.code}: {'; '.join(error.messages)}")
    following = next_line(line) if closing != line.closing_reading else None
    if following is not None and following.closing_reading is not None:
        try:
            calculate_line(closing, following.closing_reading, following.testing_litres, following.price_per_litre,
                           meter_reset=following.meter_reset, before_reset=following.reading_before_reset,
                           after_reset=following.reading_after_reset)
        except ValidationError as error:
            raise ValidationError(
                f"Nozzle {line.nozzle.code}: the next shift ({_sheet_label(following.sheet)}) starts from this "
                f"closing reading and would become invalid: {'; '.join(error.messages)}"
            )
    return following


@transaction.atomic
def request_correction(sheet, *, user, reason, changes, request=None):
    """
    `changes` is a list of (line, new_closing, new_testing, new_price) for the
    lines that differ. Nothing changes on the sheet until the Dealer approves.
    """
    sheet = _lock(sheet)
    if not user.accessible_outlets().filter(pk=sheet.outlet_id).exists():
        raise PermissionDenied("You are not assigned to this outlet.")
    if sheet.status != Status.APPROVED:
        raise ValidationError("Corrections are only for approved sheets. Draft sheets can be edited directly.")
    if sheet.has_pending_correction:
        raise ValidationError("This sheet already has a correction awaiting approval.")
    if not reason.strip():
        raise ValidationError("Explain why the approved figures are wrong.")
    if not changes:
        raise ValidationError("Change at least one value.")
    for line, closing, testing, price in changes:
        _check_change(line, closing, testing, price)

    correction = SalesCorrection.objects.create(
        business=sheet.business, sheet=sheet, reason=reason.strip(), requested_by=user
    )
    for line, closing, testing, price in changes:
        CorrectionLine.objects.create(
            business=sheet.business, correction=correction, line=line,
            old_closing_reading=line.closing_reading, new_closing_reading=closing,
            old_testing_litres=line.testing_litres, new_testing_litres=testing,
            old_price_per_litre=line.price_per_litre, new_price_per_litre=price,
        )
    AuditLog.record(AuditLog.Action.CREATE, f"Requested a correction to {sheet}", user=user, obj=correction,
                    changes={"reason": correction.reason}, request=request)
    return correction


@transaction.atomic
def approve_correction(correction, *, user, note="", request=None):
    _require_dealer(user)
    correction = SalesCorrection.objects.select_for_update().get(pk=correction.pk)
    if correction.status != SalesCorrection.Status.PENDING:
        raise ValidationError("This correction has already been reviewed.")
    _lock(correction.sheet)

    history = {}
    for item in correction.lines.select_related("line__nozzle"):
        line = DailySalesLine.objects.select_for_update().get(pk=item.line_id)
        if (line.closing_reading, line.testing_litres, line.price_per_litre) != (
            item.old_closing_reading, item.old_testing_litres, item.old_price_per_litre
        ):
            raise ValidationError(f"Nozzle {line.nozzle.code} changed after this correction was requested. Reject it and ask for a new one.")
        following = _check_change(line, item.new_closing_reading, item.new_testing_litres, item.new_price_per_litre)

        if following is not None:
            item.next_line = following
            item.next_old_opening = following.opening_reading
            item.next_new_opening = item.new_closing_reading
            following.opening_reading = item.new_closing_reading
            following.save()  # recalculates that line's figures
        line.closing_reading = item.new_closing_reading
        line.testing_litres = item.new_testing_litres
        line.price_per_litre = item.new_price_per_litre
        line.save()
        item.save()
        history[line.nozzle.code] = {
            "closing_reading": [str(item.old_closing_reading), str(item.new_closing_reading)],
            "testing_litres": [str(item.old_testing_litres), str(item.new_testing_litres)],
            "price_per_litre": [str(item.old_price_per_litre), str(item.new_price_per_litre)],
            **({"next_shift_opening": [str(item.next_old_opening), str(item.next_new_opening)]} if following else {}),
        }

    correction.status = SalesCorrection.Status.APPROVED
    correction.reviewed_by, correction.reviewed_at = user, timezone.now()
    correction.review_note = note.strip()
    correction.save()
    AuditLog.record(AuditLog.Action.CORRECT, f"Approved correction to {correction.sheet}", user=user,
                    obj=correction.sheet, changes=history, request=request)
    return correction


@transaction.atomic
def reject_correction(correction, *, user, note, request=None):
    _require_dealer(user)
    correction = SalesCorrection.objects.select_for_update().get(pk=correction.pk)
    if correction.status != SalesCorrection.Status.PENDING:
        raise ValidationError("This correction has already been reviewed.")
    if not note.strip():
        raise ValidationError("Write a note explaining why the correction is rejected.")
    correction.status = SalesCorrection.Status.REJECTED
    correction.reviewed_by, correction.reviewed_at = user, timezone.now()
    correction.review_note = note.strip()
    correction.save()
    AuditLog.record(AuditLog.Action.REJECT, f"Rejected correction to {correction.sheet}", user=user,
                    obj=correction.sheet, changes={"note": correction.review_note}, request=request)
    return correction
