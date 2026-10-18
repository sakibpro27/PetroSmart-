"""
Shift Card rules. Every save happens in this module, inside one database
transaction, with permissions checked on the server and an audit-log entry.

There is no approval step: a saved card is final. To keep every nozzle's
reading history consistent:

1. A nozzle's readings are entered in (date, shift order) sequence, and a
   nozzle can appear on only one card per shift.
2. Opening readings come from the nozzle's previous closing reading (or its
   starting reading) and cannot be typed over.
3. A card can be edited or deleted only while no later card starts from its
   closing readings, and before that day's tank stock is saved. An older card
   is fixed with a correction, which also updates the next card's opening
   reading and keeps the old and new values.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from audit.models import AuditLog
from station.models import FuelPrice, Nozzle
from tenants.models import Outlet

from .calculations import calculate_line
from .models import CorrectionLine, DailySalesLine, DailySalesSheet, SalesCorrection

ZERO = Decimal("0")
HEADER_FIELDS = (
    "employee", "cashier_name", "helper_name", "tanker_card", "time_from", "time_to", "notes",
    "general_credit", "general_credit_party", "bank_card", "company_card", "phone_wallet",
    "notes_2000", "notes_500", "notes_200", "notes_100", "notes_50", "notes_20", "notes_10", "coins",
)
LINE_FIELDS = ("closing_reading", "testing_litres", "meter_reset", "reading_before_reset", "reading_after_reset", "notes")


# --- Who may see and change what ---------------------------------------------


def viewable_outlets(user):
    """Dealers see every outlet (inactive ones too, for history); managers their assigned ones."""
    if user.is_dealer:
        return Outlet.objects.for_business(user.business)
    return user.accessible_outlets()


def sheets_for(user):
    return DailySalesSheet.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


def _require_outlet(user, outlet):
    if not user.accessible_outlets().filter(pk=outlet.pk).exists():
        raise PermissionDenied("You are not assigned to this outlet.")


def _stock_locked(outlet, day):
    from stock.services import stock_locked  # imported here: the stock app builds on sales

    return stock_locked(outlet, day)


def change_block_reason(sheet):
    """Why the card can no longer be edited or deleted directly, or None if it can."""
    if sheet.has_later_readings():
        return "A later shift card already starts from these closing readings. Use Correct instead."
    if _stock_locked(sheet.outlet, sheet.business_date):
        return "Tank stock for this date is already saved. Delete or edit that stock sheet first."
    return None


def can_change(sheet, user):
    return user.accessible_outlets().filter(pk=sheet.outlet_id).exists() and change_block_reason(sheet) is None


def _label(day, shift):
    return f"{day:%d %b %Y}, {shift.name} shift"


# --- Reading history -------------------------------------------------------------


def _before_q(day, order, prefix="sheet__"):
    return Q(**{f"{prefix}business_date__lt": day}) | Q(**{f"{prefix}business_date": day, f"{prefix}shift_sort_order__lt": order})


def previous_line(nozzle, day, order):
    """The nozzle's line on the closest earlier shift, or None."""
    return (DailySalesLine.objects.filter(nozzle=nozzle).filter(_before_q(day, order))
            .order_by("-sheet__business_date", "-sheet__shift_sort_order").first())


def next_line(line):
    """The same nozzle's line on the closest later shift, or None."""
    return (DailySalesLine.objects.filter(nozzle=line.nozzle).filter(line.sheet._later_q("sheet__"))
            .order_by("sheet__business_date", "sheet__shift_sort_order").first())


def nozzle_rows(dispenser, day, shift):
    """
    The nozzles of an MPD/DU for a new card, with opening reading and rate,
    or a ValidationError explaining why a card cannot be started.
    """
    nozzles = list(Nozzle.objects.filter(dispenser=dispenser, is_active=True).select_related("product", "tank"))
    if not nozzles:
        raise ValidationError(f"{dispenser} has no active nozzles. The Dealer sets them up under Outlets.")
    rows, problems = [], []
    for nozzle in nozzles:
        clash = (DailySalesLine.objects.filter(nozzle=nozzle)
                 .exclude(_before_q(day, shift.sort_order)).select_related("sheet__shift").order_by("-sheet__business_date").first())
        if clash is not None:
            problems.append(f"Nozzle {nozzle.code} already has a reading for "
                            f"{_label(clash.sheet.business_date, clash.sheet.shift)}. Readings must be entered in order.")
            continue
        price = FuelPrice.price_on(dispenser.outlet, nozzle.product, day)
        if price is None:
            problems.append(f"No selling price is set at {dispenser.outlet.code} for {nozzle.product.name} on {day:%d %b %Y}.")
            continue
        before = previous_line(nozzle, day, shift.sort_order)
        rows.append({"nozzle": nozzle, "opening": before.closing_reading if before else nozzle.initial_reading,
                     "price": price.price_per_litre})
    if problems:
        raise ValidationError(problems)
    return rows


# --- Money ---------------------------------------------------------------------------


def card_figures(sheet):
    """
    The right-hand panel of the card.

        Cash to be collected = Total fuel + Lube/oil sale + Customer receipts
                               - Credit sale - Gen. credit - Bank card
                               - Company card - Phone wallet - Exp/cash by DSM
        Balance (short / excess) = Cash collection (notes + coins) - Cash to be collected
    """
    fuel = sheet.lines.aggregate(total=Sum("sales_value"))["total"] or ZERO
    lube = sum((abs(m.quantity) * (m.unit_price or ZERO) for m in sheet.lube_sales.all()), ZERO).quantize(Decimal("0.01"))
    receipts = sheet.customer_receipts.aggregate(total=Sum("amount"))["total"] or ZERO
    credit = sheet.credit_sales.aggregate(total=Sum("amount"))["total"] or ZERO
    expenses = sheet.dsm_expenses.aggregate(total=Sum("amount"))["total"] or ZERO
    cash = sheet.cash_collection
    expected = (fuel + lube + receipts - credit - sheet.general_credit - sheet.bank_card - sheet.company_card
                - sheet.phone_wallet - expenses)
    return {
        "total_fuel": fuel, "lube": lube, "customer_receipts": receipts, "cash_collection": cash, "credit": credit,
        "general_credit": sheet.general_credit, "bank_card": sheet.bank_card, "company_card": sheet.company_card,
        "phone_wallet": sheet.phone_wallet, "expenses": expenses, "expected_cash": expected, "balance": cash - expected,
    }


# --- Saving a card --------------------------------------------------------------------


@transaction.atomic
def save_card(*, user, header, rows, credits=(), receipts=(), lubes=(), expenses=(), sheet=None, request=None):
    """
    Create (sheet=None) or update a Shift Card with everything on it.

    header:   cleaned CardHeaderForm data (business_date, shift, dispenser, employee, money fields...)
    rows:     [{"nozzle": Nozzle, "closing_reading": ..., "testing_litres": ..., ...}]
    credits:  [(customer, amount, vehicle_number, slip_number)]
    receipts: [(customer, amount, reference)]
    lubes:    [(item, quantity, rate)]
    expenses: [(category, description, amount)]
    Returns (sheet, warnings).
    """
    # Imported here to avoid import cycles: these apps build on sales.
    from finance.models import CreditSale, CustomerPayment, Expense, cash_method
    from operations.models import StockMovement

    is_new = sheet is None
    if is_new:
        dispenser, shift, day = header["dispenser"], header["shift"], header["business_date"]
        outlet = dispenser.outlet
        _require_outlet(user, outlet)
        if shift.outlet_id != outlet.pk:
            raise ValidationError("The shift and the MPD / DU must belong to the same outlet.")
        if day > timezone.localdate():
            raise ValidationError("A shift card cannot be dated in the future.")
        if _stock_locked(outlet, day):
            raise ValidationError(f"Tank stock for {outlet.code} on {day:%d %b %Y} is already saved. "
                                  "Delete or edit that stock sheet first.")
        planned = {r["nozzle"].pk: r for r in nozzle_rows(dispenser, day, shift)}
        before = None
    else:
        sheet = DailySalesSheet.objects.select_for_update().select_related("outlet", "shift").get(pk=sheet.pk)
        outlet, day = sheet.outlet, sheet.business_date
        _require_outlet(user, outlet)
        reason = change_block_reason(sheet)
        if reason:
            raise ValidationError(reason)
        planned = {line.nozzle_id: line for line in sheet.lines.all()}
        before = card_figures(sheet)

    if set(planned) != {row["nozzle"].pk for row in rows}:
        raise ValidationError("The nozzle rows do not match this MPD / DU. Reload the page and try again.")
    employee = header.get("employee")
    if employee is not None and (employee.outlet_id != outlet.pk or employee.business_id != user.business_id):
        raise ValidationError("This employee works at a different outlet.")

    if is_new:
        sheet = DailySalesSheet(business=user.business, outlet=outlet, shift=header["shift"], business_date=day,
                                shift_sort_order=header["shift"].sort_order, dispenser=header["dispenser"],
                                entered_by=user)
    else:
        sheet.updated_by = user
    for field in HEADER_FIELDS:
        if field in header:
            setattr(sheet, field, header[field])
    sheet.full_clean()
    sheet.save()

    # Nozzle lines
    for row in rows:
        nozzle = row["nozzle"]
        if is_new:
            plan = planned[nozzle.pk]
            line = DailySalesLine(business=sheet.business, sheet=sheet, nozzle=nozzle, product=nozzle.product,
                                  tank=nozzle.tank, opening_reading=plan["opening"], price_per_litre=plan["price"])
        else:
            line = planned[nozzle.pk]
        for field in LINE_FIELDS:
            if field in row:
                setattr(line, field, row[field])
        try:
            line.full_clean()
        except ValidationError as error:
            raise ValidationError(f"Nozzle {nozzle.code}: {'; '.join(error.messages)}")
        line.save()

    # Linked records are replaced as a whole on every save.
    if not is_new:
        sheet.credit_sales.all().delete()
        sheet.customer_receipts.all().delete()
        sheet.dsm_expenses.all().delete()
        sheet.lube_sales.all().delete()

    for customer, amount, vehicle, slip in credits:
        CreditSale.objects.create(business=sheet.business, sheet=sheet, customer=customer, amount=amount,
                                  vehicle_number=vehicle, slip_number=slip)
    cash = cash_method(sheet.business) if (receipts or expenses) else None
    for customer, amount, reference in receipts:
        CustomerPayment.objects.create(business=sheet.business, customer=customer, outlet=outlet, received_on=day,
                                       amount=amount, method=cash, reference=reference,
                                       notes="Received on shift card", entered_by=user, sheet=sheet)
    sold = {}
    for item, quantity, rate in lubes:
        sold[item] = sold.get(item, ZERO) + quantity
    for item, quantity in sold.items():
        on_hand = item.stock_at(outlet)
        if quantity > on_hand:
            raise ValidationError(f"Only {on_hand:.2f} of {item} are in stock at {outlet.code}.")
    for item, quantity, rate in lubes:
        StockMovement.objects.create(business=sheet.business, item=item, outlet=outlet, moved_on=day,
                                     kind=StockMovement.Kind.SALE, quantity=-quantity, unit_price=rate,
                                     reference="Shift card", entered_by=user, sales_sheet=sheet)
    for category, description, amount in expenses:
        Expense.objects.create(business=sheet.business, outlet=outlet, expense_date=day, category=category,
                               description=description, amount=amount, method=cash,
                               paid_to=str(sheet.employee or ""), entered_by=user, sheet=sheet)

    after = card_figures(sheet)
    summary = {key: f"{value:.2f}" for key, value in after.items()}
    if is_new:
        AuditLog.record(AuditLog.Action.CREATE, f"Saved shift card {sheet}", user=user, obj=sheet,
                        changes=summary, request=request)
    else:
        changed = {key: {"from": f"{before[key]:.2f}", "to": summary[key]} for key in after if before[key] != after[key]}
        AuditLog.record(AuditLog.Action.UPDATE, f"Edited shift card {sheet}", user=user, obj=sheet,
                        changes=changed, request=request)

    warnings = [f"{c.name} is now over their credit limit of ₹{c.credit_limit}."
                for c in {customer for customer, *_ in credits}
                if c.credit_limit is not None and c.balance() > c.credit_limit]
    return sheet, warnings


@transaction.atomic
def delete_card(sheet, *, user, request=None):
    sheet = DailySalesSheet.objects.select_for_update().get(pk=sheet.pk)
    _require_outlet(user, sheet.outlet)
    reason = change_block_reason(sheet)
    if reason:
        raise ValidationError(reason.replace("Use Correct instead.", "It cannot be deleted."))
    snapshot = {key: f"{value:.2f}" for key, value in card_figures(sheet).items()}
    snapshot["readings"] = {line.nozzle.code: [str(line.opening_reading), str(line.closing_reading), str(line.testing_litres)]
                            for line in sheet.lines.select_related("nozzle")}
    AuditLog.record(AuditLog.Action.DELETE, f"Deleted shift card {sheet}", user=user, obj=sheet,
                    changes=snapshot, request=request)
    sheet.credit_sales.all().delete()
    sheet.customer_receipts.all().delete()
    sheet.dsm_expenses.all().delete()
    sheet.lube_sales.all().delete()
    sheet.delete()


# --- Corrections to older cards ----------------------------------------------------------


def _check_change(line, closing, testing, price):
    """Validate one change, including its effect on the next card's line for the same nozzle."""
    try:
        calculate_line(line.opening_reading, closing, testing, price, meter_reset=line.meter_reset,
                       before_reset=line.reading_before_reset, after_reset=line.reading_after_reset)
    except ValidationError as error:
        raise ValidationError(f"Nozzle {line.nozzle.code}: {'; '.join(error.messages)}")
    following = next_line(line) if closing != line.closing_reading else None
    if following is not None:
        try:
            calculate_line(closing, following.closing_reading, following.testing_litres, following.price_per_litre,
                           meter_reset=following.meter_reset, before_reset=following.reading_before_reset,
                           after_reset=following.reading_after_reset)
        except ValidationError as error:
            raise ValidationError(
                f"Nozzle {line.nozzle.code}: the next card ({_label(following.sheet.business_date, following.sheet.shift)}) "
                f"starts from this closing reading and would become invalid: {'; '.join(error.messages)}"
            )
    return following


@transaction.atomic
def correct_card(sheet, *, user, reason, changes, request=None):
    """
    Apply a correction immediately. `changes` is a list of
    (line, new_closing, new_testing, new_price) for the lines that differ.
    """
    sheet = DailySalesSheet.objects.select_for_update().get(pk=sheet.pk)
    _require_outlet(user, sheet.outlet)
    if not reason.strip():
        raise ValidationError("Explain why the saved figures are wrong.")
    if not changes:
        raise ValidationError("Change at least one value.")

    correction = SalesCorrection.objects.create(business=sheet.business, sheet=sheet, reason=reason.strip(),
                                                requested_by=user)
    history = {}
    for line, closing, testing, price in changes:
        line = DailySalesLine.objects.select_for_update().select_related("nozzle").get(pk=line.pk)
        following = _check_change(line, closing, testing, price)
        item = CorrectionLine(business=sheet.business, correction=correction, line=line,
                              old_closing_reading=line.closing_reading, new_closing_reading=closing,
                              old_testing_litres=line.testing_litres, new_testing_litres=testing,
                              old_price_per_litre=line.price_per_litre, new_price_per_litre=price)
        if following is not None:
            item.next_line, item.next_old_opening, item.next_new_opening = following, following.opening_reading, closing
            following.opening_reading = closing
            following.save()  # recalculates that line's figures
        line.closing_reading, line.testing_litres, line.price_per_litre = closing, testing, price
        line.save()
        item.save()
        history[line.nozzle.code] = {
            "closing_reading": [str(item.old_closing_reading), str(closing)],
            "testing_litres": [str(item.old_testing_litres), str(testing)],
            "price_per_litre": [str(item.old_price_per_litre), str(price)],
            **({"next_card_opening": [str(item.next_old_opening), str(closing)]} if following else {}),
        }
    AuditLog.record(AuditLog.Action.CORRECT, f"Corrected shift card {sheet}", user=user, obj=sheet,
                    changes={"reason": correction.reason, **history}, request=request)
    return correction
