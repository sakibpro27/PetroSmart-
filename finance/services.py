"""
Collections, customer credit and expenses: the rules, permission checks and
audit logging. Views only collect input and display results.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from audit.models import AuditLog
from sales.models import DailySalesLine, DailySalesSheet
from sales.services import viewable_outlets

from .models import (
    CollectionLine, CreditAdjustment, CreditCustomer, CreditSale, CustomerPayment, Expense, PaymentMethod,
    ShiftCollection,
)

ZERO = Decimal("0")
Status = ShiftCollection.Status


def _require_dealer(user):
    if not user.is_dealer:
        raise PermissionDenied("Only the Dealer can do this.")


def _require_outlet(user, outlet):
    if not user.accessible_outlets().filter(pk=outlet.pk).exists():
        raise PermissionDenied("You are not assigned to this outlet.")


def _not_future(day, what):
    if day > timezone.localdate():
        raise ValidationError(f"{what} cannot be dated in the future.")


# --- Shift collections ----------------------------------------------------------


def collections_for(user):
    return ShiftCollection.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


def can_edit_collection(collection, user):
    return collection.status == Status.OPEN and user.accessible_outlets().filter(pk=collection.outlet_id).exists()


def matching_sales(collection):
    """The Daily Sales sheet for the same outlet, date and shift, and its customer sales value."""
    sheet = DailySalesSheet.objects.filter(outlet=collection.outlet, business_date=collection.business_date,
                                           shift=collection.shift).first()
    value = None
    if sheet is not None:
        value = DailySalesLine.objects.filter(sheet=sheet).aggregate(total=Sum("sales_value"))["total"] or ZERO
    return sheet, value


def collection_figures(collection):
    """
    Money collected + credit sales, compared with the shift's sales value.

        Cash expected = Sales value - (UPI + card + other non-cash) - Credit sales
        Short / excess = Cash counted - Cash expected
                       = (all money collected + credit) - Sales value
    """
    payments = collection.payments_total()
    credit = collection.credit_total()
    cash = collection.lines.filter(method__kind=PaymentMethod.Kind.CASH).aggregate(total=Sum("amount"))["total"] or ZERO
    non_cash = payments - cash
    sheet, sales_value = matching_sales(collection)
    accounted = payments + credit
    return {
        "payments": payments, "credit": credit, "accounted": accounted, "sales_sheet": sheet,
        "sales_value": sales_value, "cash": cash, "non_cash": non_cash,
        "expected_cash": None if sales_value is None else sales_value - non_cash - credit,
        "difference": None if sales_value is None else accounted - sales_value,
    }


def collection_for_sheet(sheet, user):
    """The collection entry for a Daily Sales sheet's outlet, date and shift, created if needed."""
    collection = ShiftCollection.objects.filter(outlet=sheet.outlet, business_date=sheet.business_date,
                                                shift=sheet.shift).first()
    if collection is None and user.accessible_outlets().filter(pk=sheet.outlet_id).exists():
        collection = create_collection(user=user, shift=sheet.shift, business_date=sheet.business_date)
    return collection


@transaction.atomic
def create_collection(*, user, shift, business_date, request=None):
    _require_outlet(user, shift.outlet)
    _not_future(business_date, "Collections")
    if ShiftCollection.objects.filter(outlet=shift.outlet, business_date=business_date, shift=shift).exists():
        raise ValidationError("Collections for this outlet, date and shift are already recorded. Open that entry instead.")
    collection = ShiftCollection.objects.create(business=user.business, outlet=shift.outlet, shift=shift,
                                                business_date=business_date, entered_by=user)
    for method in PaymentMethod.objects.for_business(user.business).filter(is_active=True):
        CollectionLine.objects.create(business=user.business, collection=collection, method=method)
    AuditLog.record(AuditLog.Action.CREATE, f"Started {collection}", user=user, obj=collection, request=request)
    return collection


@transaction.atomic
def save_collection(collection, line_formset, credit_formset, notes_form, *, user, request=None):
    collection = ShiftCollection.objects.select_for_update().get(pk=collection.pk)
    if not can_edit_collection(collection, user):
        raise ValidationError("These collections are verified and locked.")
    line_ids = set(collection.lines.values_list("pk", flat=True))
    if any(form.instance.pk not in line_ids for form in line_formset.forms):
        raise ValidationError("These amounts do not match this entry. Reload the page and try again.")
    credit_ids = set(collection.credit_sales.values_list("pk", flat=True))
    if any(form.instance.pk and form.instance.pk not in credit_ids for form in credit_formset.forms):
        raise ValidationError("These credit sales do not match this entry. Reload the page and try again.")

    before = collection_figures(collection)
    line_formset.save()
    for credit in credit_formset.save(commit=False):
        credit.business, credit.collection = collection.business, collection
        credit.save()
    for credit in credit_formset.deleted_objects:
        credit.delete()
    if notes_form is not None:
        notes_form.save()
    after = collection_figures(collection)
    notes_changed = notes_form is not None and notes_form.has_changed()
    if (before["payments"], before["credit"]) != (after["payments"], after["credit"]) or notes_changed:
        AuditLog.record(AuditLog.Action.UPDATE, f"Updated {collection}", user=user, obj=collection, request=request,
                        changes={"payments": [str(before["payments"]), str(after["payments"])],
                                 "credit_sales": [str(before["credit"]), str(after["credit"])],
                                 "by_method": {line.method.name: str(line.amount)
                                               for line in collection.lines.select_related("method")}})
    return collection


def customers_over_limit(collection):
    return [sale.customer for sale in collection.credit_sales.select_related("customer")
            if sale.customer.credit_limit is not None and sale.customer.balance() > sale.customer.credit_limit]


@transaction.atomic
def verify_collection(collection, *, user, request=None):
    _require_dealer(user)
    collection = ShiftCollection.objects.select_for_update().get(pk=collection.pk)
    if collection.status != Status.OPEN:
        raise ValidationError("These collections are already verified.")
    figures = collection_figures(collection)
    collection.status = Status.VERIFIED
    collection.verified_by, collection.verified_at = user, timezone.now()
    collection.save()
    AuditLog.record(AuditLog.Action.APPROVE, f"Verified {collection}", user=user, obj=collection, request=request,
                    changes={"accounted": str(figures["accounted"]),
                             "sales_value": None if figures["sales_value"] is None else str(figures["sales_value"]),
                             "difference": None if figures["difference"] is None else str(figures["difference"])})
    return collection


@transaction.atomic
def reopen_collection(collection, *, user, note, request=None):
    _require_dealer(user)
    if not note.strip():
        raise ValidationError("Write a note explaining why these collections are reopened.")
    collection = ShiftCollection.objects.select_for_update().get(pk=collection.pk)
    if collection.status != Status.VERIFIED:
        raise ValidationError("Only verified collections can be reopened.")
    collection.status = Status.OPEN
    collection.verified_by = collection.verified_at = None
    collection.save()
    AuditLog.record(AuditLog.Action.UPDATE, f"Reopened {collection}", user=user, obj=collection, request=request,
                    changes={"note": note.strip()})
    return collection


# --- Customer credit --------------------------------------------------------------------


def ledger(customer):
    """
    Every entry that changed the customer's balance, oldest first, with a
    running balance. Debit = the customer owes more; credit = owes less.
    """
    rows = [{"date": customer.opening_balance_date, "kind": "Opening balance", "detail": "",
             "debit": customer.opening_balance, "credit": ZERO, "order": 0}]
    for sale in customer.credit_sales.select_related("collection__outlet", "collection__shift"):
        c = sale.collection
        rows.append({"date": c.business_date, "kind": "Credit sale",
                     "detail": f"{c.outlet.code} · {c.shift.name}" + (f" · {sale.vehicle_number}" if sale.vehicle_number else "")
                     + (f" · slip {sale.slip_number}" if sale.slip_number else ""),
                     "debit": sale.amount, "credit": ZERO, "order": 1, "link": c.get_absolute_url()})
    for payment in customer.payments.select_related("method"):
        rows.append({"date": payment.received_on, "kind": "Payment received",
                     "detail": f"{payment.method.name}" + (f" · {payment.reference}" if payment.reference else ""),
                     "debit": ZERO, "credit": payment.amount, "order": 2, "payment": payment})
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
        _require_outlet(user, Expense.objects.get(pk=expense.pk).outlet)
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
    _require_outlet(user, expense.outlet)
    AuditLog.record(AuditLog.Action.DELETE, f"Deleted expense {expense}", user=user, obj=expense, request=request,
                    changes={"amount": f"{expense.amount:.2f}", "category": str(expense.category),
                             "expense_date": str(expense.expense_date), "description": expense.description})
    expense.delete()


# --- Operational summary ---------------------------------------------------------------


def operational_summary(*, business, outlets, date_from, date_to):
    """
    Approved customer sales value against money collected, credit given and
    expenses for a period. For management use, not a statutory account.
    """
    sales_value = DailySalesLine.objects.filter(
        business=business, sheet__outlet__in=outlets, sheet__business_date__range=(date_from, date_to),
        sheet__status=DailySalesSheet.Status.APPROVED,
    ).aggregate(total=Sum("sales_value"))["total"] or ZERO
    collections = ShiftCollection.objects.filter(business=business, outlet__in=outlets,
                                                 business_date__range=(date_from, date_to))
    by_method = list(
        CollectionLine.objects.filter(collection__in=collections).values("method__name")
        .annotate(total=Sum("amount")).order_by("method__sort_order", "method__name")
    )
    collected = sum((row["total"] or ZERO for row in by_method), ZERO)
    credit = CreditSale.objects.filter(collection__in=collections).aggregate(total=Sum("amount"))["total"] or ZERO
    expenses = Expense.objects.filter(business=business, outlet__in=outlets, expense_date__range=(date_from, date_to))
    by_category = list(expenses.values("category__name").annotate(total=Sum("amount")).order_by("category__name"))
    recovered = CustomerPayment.objects.filter(business=business, outlet__in=outlets,
                                               received_on__range=(date_from, date_to)).aggregate(total=Sum("amount"))["total"] or ZERO
    return {
        "sales_value": sales_value, "by_method": by_method, "collected": collected, "credit": credit,
        "difference": collected + credit - sales_value,
        "by_category": by_category, "expenses": expenses.aggregate(total=Sum("amount"))["total"] or ZERO,
        "credit_recovered": recovered,
    }
