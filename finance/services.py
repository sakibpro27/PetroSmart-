"""
Customer credit, expenses and the operational summary: the rules, permission
checks and audit logging. Money collected on each shift is recorded on the
Shift Card (sales app); its credit sales, receipts and expenses are stored
here so ledgers and reports include them.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from audit.models import AuditLog
from sales.models import DailySalesLine, DailySalesSheet
from sales.services import viewable_outlets

from .models import CreditCustomer, CreditSale, CustomerPayment, Expense

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
    for sale in customer.credit_sales.select_related("sheet__outlet", "sheet__shift", "sheet__dispenser"):
        card = sale.sheet
        rows.append({"date": card.business_date, "kind": "Credit sale",
                     "detail": f"{card.outlet.code} · {card.shift.name}" + (f" · {sale.vehicle_number}" if sale.vehicle_number else "")
                     + (f" · slip {sale.slip_number}" if sale.slip_number else ""),
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
