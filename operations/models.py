"""
Phase 8: lubricant and shop inventory, employees and shift attendance, and
compliance / maintenance reminders.

Employees are staff records only. They do not log in: PetroSmart still has
exactly two login roles inside a business (Dealer and Manager).
"""

import calendar
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum

from station.models import Shift, check_same_business
from tenants.models import Outlet, TenantOwnedModel

QTY = {"max_digits": 12, "decimal_places": 2}
ZERO = Decimal("0")


# --- Shop inventory -------------------------------------------------------------


class ShopItem(TenantOwnedModel):
    class Category(models.TextChoices):
        LUBRICANT = "LUBRICANT", "Lubricant / engine oil"
        COOLANT = "COOLANT", "Coolant / additive"
        SHOP = "SHOP", "Shop item"
        OTHER = "OTHER", "Other"

    class Unit(models.TextChoices):
        PIECE = "PIECE", "Piece"
        LITRE = "LITRE", "Litre"
        PACK = "PACK", "Pack"

    name = models.CharField(max_length=120, help_text="e.g. 20W-40 engine oil, 1 L can")
    sku = models.CharField("SKU / code", max_length=40, blank=True)
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.LUBRICANT)
    unit = models.CharField(max_length=5, choices=Unit.choices, default=Unit.PIECE)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))],
                                        help_text="Default selling price per unit (₹).")
    reorder_level = models.DecimalField(**QTY, default=ZERO, validators=[MinValueValidator(Decimal("0"))],
                                        help_text="Show a low-stock alert at or below this quantity.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["business", "name"], name="unique_shop_item_per_business",
                                               violation_error_message="An item with this name already exists.")]

    def __str__(self):
        return self.name

    def stock_at(self, outlet):
        return self.movements.filter(outlet=outlet).aggregate(total=Sum("quantity"))["total"] or ZERO


class StockMovement(TenantOwnedModel):
    """
    Every change to an item's stock at an outlet. Stock on hand is the sum of
    the quantities: purchases and openings are positive, sales negative,
    adjustments either.
    """

    class Kind(models.TextChoices):
        OPENING = "OPENING", "Opening stock"
        PURCHASE = "PURCHASE", "Purchase"
        SALE = "SALE", "Sale"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    item = models.ForeignKey(ShopItem, on_delete=models.PROTECT, related_name="movements")
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="shop_movements")
    moved_on = models.DateField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    quantity = models.DecimalField(**QTY, help_text="Positive adds to stock, negative removes it.")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                     validators=[MinValueValidator(Decimal("0"))])
    reference = models.CharField(max_length=60, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when the item was sold at the pump and recorded on a Shift Card (Lube/Oil Sale).
    sales_sheet = models.ForeignKey("sales.DailySalesSheet", on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="lube_sales", verbose_name="shift card")

    class Meta:
        ordering = ["-moved_on", "-pk"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.item}"

    @property
    def amount(self):
        if self.unit_price is None:
            return None
        return abs(self.quantity) * self.unit_price

    def clean(self):
        super().clean()
        check_same_business(self, "item", "outlet")
        if self.quantity is None:
            return
        if self.quantity == 0:
            raise ValidationError({"quantity": "Quantity cannot be zero."})
        if self.kind == self.Kind.SALE and self.quantity > 0:
            raise ValidationError({"quantity": "Sales reduce stock, so the quantity is stored as negative."})
        if self.kind in (self.Kind.OPENING, self.Kind.PURCHASE) and self.quantity < 0:
            raise ValidationError({"quantity": "Openings and purchases add stock."})


# --- Employees and attendance -------------------------------------------------------


class Employee(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="employees")
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    job_title = models.CharField(max_length=60, default="Pump attendant", help_text="e.g. Pump attendant, Cashier, Helper")
    joined_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["outlet", "name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        check_same_business(self, "outlet")


class Attendance(TenantOwnedModel):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        ABSENT = "ABSENT", "Absent"
        LEAVE = "LEAVE", "On leave"
        HALF = "HALF", "Half shift"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance")
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="attendance")
    work_date = models.DateField()
    status = models.CharField(max_length=7, choices=Status.choices, default=Status.PRESENT)
    duty = models.CharField(max_length=60, blank=True, help_text="e.g. Nozzles N1–N2, cash counter")
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-work_date", "shift__sort_order", "employee__name"]
        constraints = [models.UniqueConstraint(fields=["employee", "work_date", "shift"], name="unique_attendance_per_shift")]

    def clean(self):
        super().clean()
        check_same_business(self, "employee", "shift")
        if self.employee_id and self.shift_id and self.employee.outlet_id != self.shift.outlet_id:
            raise ValidationError({"shift": "This shift is at a different outlet from the employee."})


# --- Reminders ----------------------------------------------------------------------


def add_months(day, months):
    """Same day of the month `months` later, clipped to the month's end (31 Jan + 1 month = 28/29 Feb)."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


class Reminder(TenantOwnedModel):
    class Category(models.TextChoices):
        LICENCE = "LICENCE", "Licence / permit renewal"
        CALIBRATION = "CALIBRATION", "Dispenser calibration / stamping"
        SAFETY = "SAFETY", "Fire and safety check"
        ENVIRONMENT = "ENVIRONMENT", "Environment / pollution compliance"
        MAINTENANCE = "MAINTENANCE", "Equipment maintenance"
        TANK = "TANK", "Tank cleaning / inspection"
        INSURANCE = "INSURANCE", "Insurance renewal"
        OTHER = "OTHER", "Other"

    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, null=True, blank=True, related_name="reminders",
                               help_text="Leave empty for a reminder that covers the whole business.")
    title = models.CharField(max_length=150)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.OTHER)
    due_date = models.DateField()
    repeat_months = models.PositiveSmallIntegerField(
        default=0, help_text="0 = does not repeat. Otherwise the next reminder is created this many months after "
        "the due date when this one is marked done.")
    notes = models.TextField(blank=True, help_text="Authority, licence number, contact, documents needed, etc.")
    completed_on = models.DateField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    completion_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["completed_on", "due_date"]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        check_same_business(self, "outlet")
