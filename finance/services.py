"""
Customer credit, expenses and the operational summary: the rules, permission
checks and audit logging. Money collected on each shift is recorded on the
Shift Card (sales app); its credit sales, receipts and expenses are stored
here so ledgers and reports include them.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from audit.models import AuditLog
from sales.models import DailySalesLine, DailySalesSheet
from sales.services import viewable_outlets
from tenants.models import Outlet

from .models import CreditBill, CreditCustomer, CreditSale, CustomerPayment, Expense, next_number

ZERO = Decimal("0")


def _require_dealer(user):
    if not user.is_dealer:
        raise PermissionDenied("Only the Dealer can do this.")


def _require_outlet(user, outlet):
    if not user.accessible_outlets().filter(pk=outlet.pk).exists():
        raise PermissionDenied("You are not assigned to this outlet.")


def _not_future(day, what):
    if day > timezone.localdate():
        raise ValidationError(f"{what} cannot be dated in the future.")


def _not_from_card(record, what):
    if record.sheet_id:
        raise ValidationError(f"This {what} was recorded on a shift card. Change it on that card instead.")


# --- Customer credit --------------------------------------------------------------------


def ledger(customer):
    """
    Every entry that changed the customer's balance, oldest first, with a
    running balance. Debit = the customer owes more; credit = owes less.
    """
    rows = [{"date": customer.opening_balance_date, "kind": "Opening balance", "detail": "",
             "debit": customer.opening_balance, "credit": ZERO, "order": 0}]
    for sale in customer.credit_sales.select_related("sheet__outlet", "sheet__shift", "sheet__dispenser", "product"):
        card = sale.sheet
        rows.append({"date": card.business_date, "kind": "Credit sale",
                     "detail": f"{card.outlet.code} · {card.shift.name}" + (f" · {sale.vehicle_number}" if sale.vehicle_number else "")
                     + f" · slip {sale.slip_no}"
                     + (f" · {sale.product.code} {sale.litres} L" if sale.product_id else ""),
                     "debit": sale.amount, "credit": ZERO, "order": 1, "link": card.get_absolute_url()})
    for payment in customer.payments.select_related("method", "sheet"):
        rows.append({"date": payment.received_on, "kind": "Payment received",
                     "detail": f"{payment.method.name}" + (f" · {payment.reference}" if payment.reference else "")
                     + (" · on shift card" if payment.sheet_id else ""),
                     "debit": ZERO, "credit": payment.amount, "order": 2,
                     "payment": None if payment.sheet_id else payment,
                     "link": payment.sheet.get_absolute_url() if payment.sheet_id else None})
    for adjustment in customer.adjustments.all():
        rows.append({"date": adjustment.adjusted_on, "kind": "Adjustment", "detail": adjustment.reason,
                     "debit": adjustment.amount if adjustment.amount > 0 else ZERO,
                     "credit": -adjustment.amount if adjustment.amount < 0 else ZERO, "order": 3})
    for bill in customer.bills.filter(status=CreditBill.Status.ISSUED).select_related("outlet"):
        # The bill adds nothing new except its round off; its slips are already listed above.
        rows.append({"date": bill.bill_date, "kind": f"Bill {bill.bill_no}",
                     "detail": f"{bill.outlet.code} · {bill.period_from:%d-%m-%Y} to {bill.bill_date:%d-%m-%Y} · "
                               f"bill amount ₹{bill.amount:,.2f}" + (" · round off" if bill.round_off else ""),
                     "debit": bill.round_off if bill.round_off > 0 else ZERO,
                     "credit": -bill.round_off if bill.round_off < 0 else ZERO, "order": 4,
                     "link": bill.get_absolute_url()})
    rows.sort(key=lambda row: (row["date"], row["order"]))
    balance = ZERO
    for row in rows:
        balance += row["debit"] - row["credit"]
        row["balance"] = balance
    return rows


@transaction.atomic
def record_payment(form, *, user, request=None):
    _require_outlet(user, form.cleaned_data["outlet"])
    _not_future(form.cleaned_data["received_on"], "A payment")
    payment = form.save(commit=False)
    payment.entered_by = user
    payment.save()
    AuditLog.record(AuditLog.Action.CREATE, f"Payment of ₹{payment.amount} from {payment.customer}", user=user,
                    obj=payment, changes=form.audit_changes(), request=request)
    return payment


@transaction.atomic
def delete_payment(payment, *, user, request=None):
    _require_dealer(user)
    _not_from_card(payment, "payment")
    AuditLog.record(AuditLog.Action.DELETE, f"Deleted payment of ₹{payment.amount} from {payment.customer}", user=user,
                    obj=payment, request=request,
                    changes={"amount": f"{payment.amount:.2f}", "received_on": str(payment.received_on),
                             "reference": payment.reference, "method": str(payment.method)})
    payment.delete()


@transaction.atomic
def record_adjustment(form, customer, *, user, request=None):
    _require_dealer(user)
    adjustment = form.save(commit=False)
    adjustment.business, adjustment.customer, adjustment.entered_by = customer.business, customer, user
    adjustment.save()
    AuditLog.record(AuditLog.Action.CORRECT, f"Adjusted {customer}'s balance by ₹{adjustment.amount}", user=user,
                    obj=customer, changes={"amount": f"{adjustment.amount:.2f}", "reason": adjustment.reason}, request=request)
    return adjustment


def outstanding_total(business):
    return sum((customer.balance() for customer in CreditCustomer.objects.for_business(business)), ZERO)


# --- Credit bills -------------------------------------------------------------------------


def bills_for(user):
    return CreditBill.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


def unbilled_slips(customer, outlet, up_to):
    """The customer's credit slips at `outlet` up to `up_to` that are not on an issued bill, oldest first."""
    return (CreditSale.objects.filter(business=customer.business, customer=customer, outlet=outlet, bill__isnull=True,
                                      sheet__business_date__lte=up_to)
            .select_related("sheet", "product").order_by("sheet__business_date", "slip_no"))


def last_bill(customer, outlet):
    return (customer.bills.filter(outlet=outlet, status=CreditBill.Status.ISSUED)
            .order_by("-bill_date", "-bill_no").first())


def bill_preview(customer, outlet, bill_date):
    """
    What a bill made now would contain: from the day after the previous bill
    (or the first unbilled slip, if older) up to `bill_date`.
    """
    slips = list(unbilled_slips(customer, outlet, bill_date))
    previous = last_bill(customer, outlet)
    if previous is not None:
        period_from = previous.bill_date + timedelta(days=1)
    else:
        period_from = slips[0].sheet.business_date if slips else customer.opening_balance_date
    if slips:
        # A card entered late for a day already billed still gets billed, on this bill.
        period_from = min(period_from, slips[0].sheet.business_date)
    total = sum((slip.amount for slip in slips), ZERO)
    round_off = total.quantize(Decimal("1"), rounding=ROUND_HALF_UP) - total
    return {"slips": slips, "period_from": period_from, "previous": previous, "total": total,
            "round_off": round_off, "amount": total + round_off}


@transaction.atomic
def create_bill(customer, outlet, bill_date, *, user, request=None):
    """
    Bill every unbilled slip of `customer` at `outlet` up to `bill_date`.
    The bill number is the next in the outlet's series. Previous balance is
    what the customer owed on the bill date apart from this bill's slips.
    """
    _require_outlet(user, outlet)
    _not_future(bill_date, "A bill")
    if customer.business_id != user.business_id or outlet.business_id != user.business_id:
        raise PermissionDenied("This customer or outlet belongs to another business.")
    Outlet.objects.select_for_update().get(pk=outlet.pk)  # one bill series per outlet
    preview = bill_preview(customer, outlet, bill_date)
    previous = preview["previous"]
    if previous is not None and bill_date < previous.bill_date:
        raise ValidationError(f"The bill date cannot be before the previous bill (no. {previous.bill_no}, "
                              f"{previous.bill_date:%d %b %Y}).")
    if not preview["slips"]:
        raise ValidationError(f"{customer} has no unbilled credit slips at {outlet.code} up to {bill_date:%d %b %Y}.")
    bill = CreditBill.objects.create(
        business=customer.business, outlet=outlet, customer=customer,
        bill_no=next_number(CreditBill.objects.filter(outlet=outlet), "bill_no"),
        bill_date=bill_date, period_from=preview["period_from"], slips_total=preview["total"],
        round_off=preview["round_off"], previous_balance=customer.balance(as_of=bill_date) - preview["total"],
        created_by=user,
    )
    CreditSale.objects.filter(pk__in=[slip.pk for slip in preview["slips"]]).update(bill=bill)
    AuditLog.record(AuditLog.Action.CREATE, f"Credit bill {bill.bill_no} to {customer} for ₹{bill.amount}", user=user,
                    obj=bill, request=request,
                    changes={"outlet": outlet.code, "period": f"{bill.period_from} to {bill.bill_date}",
                             "slips": [slip.slip_no for slip in preview["slips"]],
                             "slips_total": f"{bill.slips_total:.2f}", "round_off": f"{bill.round_off:.2f}",
                             "previous_balance": f"{bill.previous_balance:.2f}"})
    return bill


@transaction.atomic
def cancel_bill(bill, reason, *, user, request=None):
    """Dealer only. The bill number is not reused; its slips go back to unbilled for the next bill."""
    _require_dealer(user)
    _require_outlet(user, bill.outlet)
    bill = CreditBill.objects.select_for_update().get(pk=bill.pk)
    if bill.is_cancelled:
        raise ValidationError("This bill is already cancelled.")
    if not reason.strip():
        raise ValidationError("Give a reason for cancelling the bill.")
    slips = list(bill.sales.values_list("slip_no", flat=True))
    bill.sales.update(bill=None)
    bill.status, bill.cancelled_by, bill.cancelled_at = CreditBill.Status.CANCELLED, user, timezone.now()
    bill.cancel_reason = reason.strip()
    bill.save()
    AuditLog.record(AuditLog.Action.DELETE, f"Cancelled credit bill {bill.bill_no} to {bill.customer}", user=user,
                    obj=bill, request=request, changes={"reason": bill.cancel_reason, "slips": slips,
                                                        "amount": f"{bill.amount:.2f}"})
    return bill


def bill_summary(bill):
    """Litres per fuel for the bill footer, e.g. Diesel 41.94, Petrol 13.80, Other 0.00."""
    litres = {"HSD": ZERO, "MS": ZERO, "OTHER": ZERO}
    for slip in bill.sales.select_related("product"):
        key = slip.product.category if slip.product else "OTHER"
        litres[key] += slip.litres or ZERO
    return [("Diesel", litres["HSD"]), ("Petrol", litres["MS"]), ("Other", litres["OTHER"])]


# --- Expenses -----------------------------------------------------------------------------


def expenses_for(user):
    return Expense.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


@transaction.atomic
def save_expense(form, *, user, request=None):
    expense = form.instance
    is_new = expense.pk is None
    if not is_new:
        original = Expense.objects.get(pk=expense.pk)
        _not_from_card(original, "expense")
        _require_outlet(user, original.outlet)
    _require_outlet(user, form.cleaned_data["outlet"])
    _not_future(form.cleaned_data["expense_date"], "An expense")
    expense = form.save(commit=False)
    if is_new:
        expense.entered_by = user
    expense.save()
    AuditLog.record(AuditLog.Action.CREATE if is_new else AuditLog.Action.UPDATE,
                    f"{'Recorded' if is_new else 'Updated'} expense {expense}", user=user, obj=expense,
                    changes=form.audit_changes(), request=request)
    return expense


@transaction.atomic
def delete_expense(expense, *, user, request=None):
    _not_from_card(expense, "expense")
    _require_outlet(user, expense.outlet)
    AuditLog.record(AuditLog.Action.DELETE, f"Deleted expense {expense}", user=user, obj=expense, request=request,
                    changes={"amount": f"{expense.amount:.2f}", "category": str(expense.category),
                             "expense_date": str(expense.expense_date), "description": expense.description})
    expense.delete()


# --- Operational summary ---------------------------------------------------------------


def operational_summary(*, business, outlets, date_from, date_to):
    """
    The period's Shift Cards added up: fuel sales value, how it was received,
    and the cash balance, plus all expenses and customer receipts. For
    management use, not a statutory account.
    """
    from operations.models import StockMovement  # operations builds on finance

    cards = DailySalesSheet.objects.filter(business=business, outlet__in=outlets,
                                           business_date__range=(date_from, date_to))
    fuel = DailySalesLine.objects.filter(sheet__in=cards).aggregate(total=Sum("sales_value"))["total"] or ZERO
    money = cards.aggregate(bank_card=Sum("bank_card"), company_card=Sum("company_card"),
                            phone_wallet=Sum("phone_wallet"), general_credit=Sum("general_credit"))
    money = {key: value or ZERO for key, value in money.items()}
    cash = sum((card.cash_collection for card in cards), ZERO)
    lube = sum((abs(m.quantity) * (m.unit_price or ZERO) for m in StockMovement.objects.filter(sales_sheet__in=cards)), ZERO)
    card_receipts = CustomerPayment.objects.filter(sheet__in=cards).aggregate(total=Sum("amount"))["total"] or ZERO
    credit = CreditSale.objects.filter(sheet__in=cards).aggregate(total=Sum("amount"))["total"] or ZERO
    dsm_expenses = Expense.objects.filter(sheet__in=cards).aggregate(total=Sum("amount"))["total"] or ZERO
    expected_cash = (fuel + lube + card_receipts - credit - money["general_credit"] - money["bank_card"]
                     - money["company_card"] - money["phone_wallet"] - dsm_expenses)

    expenses = Expense.objects.filter(business=business, outlet__in=outlets, expense_date__range=(date_from, date_to))
    receipts = CustomerPayment.objects.filter(business=business, outlet__in=outlets,
                                              received_on__range=(date_from, date_to))
    return {
        "card_count": cards.count(), "total_fuel": fuel, "lube": lube, "card_receipts": card_receipts,
        "credit": credit, "dsm_expenses": dsm_expenses, "cash_collection": cash, "expected_cash": expected_cash,
        "balance": cash - expected_cash, **money,
        "by_category": list(expenses.values("category__name").annotate(total=Sum("amount")).order_by("category__name")),
        "expenses": expenses.aggregate(total=Sum("amount"))["total"] or ZERO,
        "credit_recovered": receipts.aggregate(total=Sum("amount"))["total"] or ZERO,
    }
