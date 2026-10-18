"""
Collections, customer credit and expenses (Phase 6).

Money collected is recorded as it actually came in, and compared with the
shift's sales value. PetroSmart never assumes collections equal sales: any
shortage or excess is shown, and credit sales are tracked per customer.

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

from station.models import Shift, check_same_business
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


# --- Shift collections ----------------------------------------------------------


class ShiftCollection(TenantOwnedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        VERIFIED = "VERIFIED", "Verified by Dealer"

    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="collections")
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="collections")
    business_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    notes = models.TextField(blank=True, help_text="Explain any shortage, excess or timing difference.")
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-business_date", "-shift__sort_order"]
        constraints = [
            models.UniqueConstraint(fields=["outlet", "business_date", "shift"], name="unique_collection_per_outlet_date_shift",
                                    violation_error_message="Collections for this outlet, date and shift are already recorded."),
        ]

    def __str__(self):
        return f"{self.outlet.code} collections {self.business_date:%d-%m-%Y} {self.shift.name}"

    def get_absolute_url(self):
        return reverse("finance:collection_detail", args=[self.pk])

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "shift")
        if self.shift_id and self.outlet_id and self.shift.outlet_id != self.outlet_id:
            raise ValidationError({"shift": "This shift belongs to a different outlet."})

    def payments_total(self):
        return self.lines.aggregate(total=Sum("amount"))["total"] or ZERO

    def credit_total(self):
        return self.credit_sales.aggregate(total=Sum("amount"))["total"] or ZERO


class CollectionLine(TenantOwnedModel):
    collection = models.ForeignKey(ShiftCollection, on_delete=models.PROTECT, related_name="lines")
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(**MONEY, default=ZERO, validators=NON_NEGATIVE)
    reference = models.CharField(max_length=100, blank=True, help_text="e.g. card settlement batch or UPI report number")

    class Meta:
        ordering = ["method__sort_order", "method__name"]
        constraints = [models.UniqueConstraint(fields=["collection", "method"], name="unique_method_per_collection")]


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
    """Fuel given on credit during a shift. Increases what the customer owes."""

    collection = models.ForeignKey(ShiftCollection, on_delete=models.PROTECT, related_name="credit_sales")
    customer = models.ForeignKey(CreditCustomer, on_delete=models.PROTECT, related_name="credit_sales")
    amount = models.DecimalField(**MONEY, validators=POSITIVE)
    vehicle_number = models.CharField(max_length=20, blank=True)
    slip_number = models.CharField(max_length=40, blank=True, help_text="Credit slip / indent number")

    class Meta:
        ordering = ["pk"]

    def clean(self):
        super().clean()
        check_same_business(self, "collection", "customer")


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

    class Meta:
        ordering = ["-expense_date", "-pk"]

    def __str__(self):
        return f"{self.description} ₹{self.amount} ({self.expense_date:%d-%m-%Y})"

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "category", "method")
