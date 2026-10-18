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

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
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

    def balance(self):
        """Amount the customer owes now: opening + credit sales - payments + adjustments."""
        sales = self.credit_sales.aggregate(total=Sum("amount"))["total"] or ZERO
        paid = self.payments.aggregate(total=Sum("amount"))["total"] or ZERO
        adjusted = self.adjustments.aggregate(total=Sum("amount"))["total"] or ZERO
        return self.opening_balance + sales - paid + adjusted


class CreditSale(TenantOwnedModel):
    """Fuel given on credit on a Shift Card. Increases what the customer owes."""

    sheet = models.ForeignKey("sales.DailySalesSheet", on_delete=models.PROTECT, related_name="credit_sales",
                              verbose_name="shift card")
    customer = models.ForeignKey(CreditCustomer, on_delete=models.PROTECT, related_name="credit_sales")
    amount = models.DecimalField(**MONEY, validators=POSITIVE)
    vehicle_number = models.CharField(max_length=20, blank=True)
    slip_number = models.CharField(max_length=40, blank=True, help_text="Credit slip / indent number")

    class Meta:
        ordering = ["pk"]

    def clean(self):
        super().clean()
        check_same_business(self, "sheet", "customer")


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
