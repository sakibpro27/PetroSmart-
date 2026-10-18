"""
Customer credit, payment methods and expenses.

The money collected on each shift is recorded on the Shift Card (sales app):
cash notes, cards, wallet, credit sales, customer receipts and expenses paid
by the attendant. Credit sales, receipts and expenses taken on a card are
stored here, linked to that card, so customer ledgers and expense reports
include them.

These records support day-to-day management. They are not a statutory
account and do not calculate GST or other taxes.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Max, Sum
from django.urls import reverse

from station.models import check_same_business
from tenants.models import Outlet, TenantOwnedModel

MONEY = {"max_digits": 14, "decimal_places": 2}
POSITIVE = [MinValueValidator(Decimal("0.01"))]
NON_NEGATIVE = [MinValueValidator(Decimal("0"))]
ZERO = Decimal("0")


class PaymentMethod(TenantOwnedModel):
    class Kind(models.TextChoices):
        CASH = "CASH", "Cash"
        UPI = "UPI", "UPI"
        CARD = "CARD", "Card"
        BANK = "BANK", "Bank transfer / cheque"
        OTHER = "OTHER", "Other"

    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=5, choices=Kind.choices)
    sort_order = models.PositiveSmallIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["business", "name"], name="unique_payment_method_per_business",
                                    violation_error_message="A payment method with this name already exists."),
        ]

    def __str__(self):
        return self.name


class ExpenseCategory(TenantOwnedModel):
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "expense categories"
        constraints = [
            models.UniqueConstraint(fields=["business", "name"], name="unique_expense_category_per_business",
                                    violation_error_message="This category already exists."),
        ]

    def __str__(self):
        return self.name


DEFAULT_METHODS = [("Cash", "CASH", 1), ("UPI", "UPI", 2), ("Card", "CARD", 3), ("Bank transfer", "BANK", 4)]
DEFAULT_CATEGORIES = ["Electricity", "Salaries and wages", "Repairs and maintenance", "Rent", "Bank charges",
                      "Office and stationery", "Other"]


def create_default_finance_setup(business):
    """Safe to call more than once."""
    for name, kind, order in DEFAULT_METHODS:
        PaymentMethod.objects.get_or_create(business=business, name=name, defaults={"kind": kind, "sort_order": order})
    for name in DEFAULT_CATEGORIES:
        ExpenseCategory.objects.get_or_create(business=business, name=name)


def cash_method(business):
    """The business's cash payment method, used for receipts and expenses taken on a Shift Card."""
    method = PaymentMethod.objects.for_business(business).filter(kind=PaymentMethod.Kind.CASH).order_by("sort_order").first()
    if method is None:
        method = PaymentMethod.objects.create(business=business, name="Cash", kind=PaymentMethod.Kind.CASH, sort_order=1)
    return method


def other_category(business):
    category, _ = ExpenseCategory.objects.get_or_create(business=business, name="Other")
    return category


# --- Customer credit ----------------------------------------------------------------


def _total(queryset, field="amount"):
    return queryset.aggregate(total=Sum(field))["total"] or ZERO


class CreditCustomer(TenantOwnedModel):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    vehicles = models.CharField(max_length=255, blank=True, help_text="Vehicle numbers, separated by commas.")
    address = models.TextField(blank=True)
    credit_limit = models.DecimalField(**MONEY, null=True, blank=True, validators=NON_NEGATIVE,
                                       help_text="Leave empty for no limit. Exceeding it shows a warning.")
    opening_balance = models.DecimalField(**MONEY, default=ZERO, validators=NON_NEGATIVE,
                                          help_text="Amount the customer already owed when added to PetroSmart.")
    opening_balance_date = models.DateField(help_text="The date of the opening balance.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["business", "name"], name="unique_credit_customer_per_business",
                                    violation_error_message="A customer with this name already exists."),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("finance:customer_ledger", args=[self.pk])

    def balance(self, as_of=None):
        """
        Amount the customer owes: opening + credit sales - payments + adjustments
        + bill round offs. With `as_of`, only entries dated on or before that day.
        """
        sales, paid = self.credit_sales.all(), self.payments.all()
        adjusted, bills = self.adjustments.all(), self.bills.filter(status=CreditBill.Status.ISSUED)
        if as_of is not None:
            sales = sales.filter(sheet__business_date__lte=as_of)
            paid, adjusted = paid.filter(received_on__lte=as_of), adjusted.filter(adjusted_on__lte=as_of)
            bills = bills.filter(bill_date__lte=as_of)
        return (self.opening_balance + _total(sales) - _total(paid) + _total(adjusted)
                + _total(bills, "round_off"))


class CreditSale(TenantOwnedModel):
    """
    Fuel given on credit on a Shift Card. Increases what the customer owes.

    The amount is what the slip is written for; litres = amount / rate, where
    the rate is the outlet's selling price for the product on the card's date.
    Slip numbers are given automatically, one series per outlet, and never
    reused. A sale on an issued bill cannot be changed until that bill is
    cancelled.
    """

    sheet = models.ForeignKey("sales.DailySalesSheet", on_delete=models.PROTECT, related_name="credit_sales",
                              verbose_name="shift card")
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="credit_sales")
    slip_no = models.PositiveIntegerField("slip no.")
    customer = models.ForeignKey(CreditCustomer, on_delete=models.PROTECT, related_name="credit_sales")
    # Empty only on credit sales recorded before products were added to slips.
    product = models.ForeignKey("station.FuelProduct", on_delete=models.PROTECT, null=True, blank=True,
                                related_name="credit_sales")
    rate = models.DecimalField("rate (₹/L)", max_digits=7, decimal_places=2, null=True, blank=True)
    litres = models.DecimalField("qty (L)", max_digits=12, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(**MONEY, validators=POSITIVE)
    vehicle_number = models.CharField(max_length=20, blank=True)
    bill = models.ForeignKey("CreditBill", on_delete=models.PROTECT, null=True, blank=True, related_name="sales")

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["outlet", "slip_no"], name="unique_slip_no_per_outlet"),
        ]

    def __str__(self):
        return f"Slip {self.slip_no} ({self.outlet.code})"

    def clean(self):
        super().clean()
        check_same_business(self, "sheet", "customer", "outlet", "product")


def litres_for(amount, rate):
    """Litres on a credit slip written for `amount` rupees at `rate` per litre, to 2 decimals."""
    return (amount / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def next_number(queryset, field):
    """The next number in a series: highest so far + 1. Call inside a transaction holding a lock."""
    return (queryset.aggregate(top=Max(field))["top"] or 0) + 1


class CustomerPayment(TenantOwnedModel):
    """Money received from a credit customer. Reduces what they owe."""

    customer = models.ForeignKey(CreditCustomer, on_delete=models.PROTECT, related_name="payments")
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="+")
    received_on = models.DateField()
    amount = models.DecimalField(**MONEY, validators=POSITIVE)
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="+")
    reference = models.CharField(max_length=100, blank=True, help_text="Receipt, cheque or UTR number")
    notes = models.CharField(max_length=255, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when the cash was taken at the pump and recorded on a Shift Card.
    sheet = models.ForeignKey("sales.DailySalesSheet", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="customer_receipts", verbose_name="shift card")

    class Meta:
        ordering = ["-received_on", "-pk"]

    def clean(self):
        super().clean()
        check_same_business(self, "customer", "outlet", "method")


class CreditAdjustment(TenantOwnedModel):
    """
    A Dealer's correction to a customer's balance (e.g. a discount or a write-off).
    Positive increases what the customer owes, negative reduces it.
    """

    customer = models.ForeignKey(CreditCustomer, on_delete=models.PROTECT, related_name="adjustments")
    adjusted_on = models.DateField()
    amount = models.DecimalField(**MONEY, help_text="Positive increases the balance; negative reduces it.")
    reason = models.CharField(max_length=255)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-adjusted_on", "-pk"]

    def clean(self):
        super().clean()
        if self.amount == 0:
            raise ValidationError({"amount": "An adjustment cannot be zero."})


class CreditBill(TenantOwnedModel):
    """
    A bill to a credit customer for one outlet's credit slips, from the day
    after their previous bill up to the bill date. Bill numbers run in one
    series per outlet and are never reused, even when a bill is cancelled.

        Bill amount = slips total + round off (to the nearest rupee)
        Net amount  = previous balance + bill amount = what the customer owes on the bill date

    The round off is part of what the customer owes, so it appears in the
    customer's ledger. Cancelling a bill frees its slips for the next bill.
    """

    class Status(models.TextChoices):
        ISSUED = "ISSUED", "Issued"
        CANCELLED = "CANCELLED", "Cancelled"

    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="credit_bills")
    customer = models.ForeignKey(CreditCustomer, on_delete=models.PROTECT, related_name="bills")
    bill_no = models.PositiveIntegerField("bill no.")
    bill_date = models.DateField(help_text="Slips up to and including this date are billed.")
    period_from = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)
    # Snapshot of the figures when the bill was made, so a reprint always matches the original.
    slips_total = models.DecimalField(**MONEY)
    round_off = models.DecimalField(**MONEY, default=ZERO)
    previous_balance = models.DecimalField(**MONEY)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-bill_date", "-bill_no"]
        constraints = [
            models.UniqueConstraint(fields=["outlet", "bill_no"], name="unique_bill_no_per_outlet"),
        ]

    def __str__(self):
        return f"Bill {self.bill_no} ({self.outlet.code}) {self.customer}"

    def get_absolute_url(self):
        return reverse("finance:bill_detail", args=[self.pk])

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "customer")

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELLED

    @property
    def amount(self):
        return self.slips_total + self.round_off

    @property
    def net_amount(self):
        return self.previous_balance + self.amount


# --- Expenses -------------------------------------------------------------------------


class Expense(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="expenses")
    expense_date = models.DateField()
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    description = models.CharField(max_length=200)
    amount = models.DecimalField(**MONEY, validators=POSITIVE)
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="+", verbose_name="paid by")
    paid_to = models.CharField(max_length=150, blank=True)
    reference = models.CharField(max_length=100, blank=True, help_text="Bill, voucher or UTR number")
    notes = models.CharField(max_length=255, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # Set for "Exp/Cash by DSM": cash paid out by the attendant and recorded on a Shift Card.
    sheet = models.ForeignKey("sales.DailySalesSheet", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="dsm_expenses", verbose_name="shift card")

    class Meta:
        ordering = ["-expense_date", "-pk"]

    def __str__(self):
        return f"{self.description} ₹{self.amount} ({self.expense_date:%d-%m-%Y})"

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "category", "method")
