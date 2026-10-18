"""
Shift Cards (Daily Sales).

* DailySalesSheet  - a Shift Card: one employee (DSM) on one MPD/DU for one
                     shift. It holds the nozzle readings and the money
                     details (cash notes, cards, wallet, credit, expenses).
                     Saved cards are final; there is no approval step.
* DailySalesLine   - one nozzle on the card: readings, testing litres,
                     rate, and the calculated figures.
* SalesCorrection  - a change to an older card whose closing readings a
  + CorrectionLine   later card already uses. Applied immediately; the old
                     and new values are kept forever.

The calculated figures are stored so that reports can add them up quickly,
but they are always produced by sales.calculations.calculate_line() from the
entered readings, never typed in.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

from station.models import LITRES, Dispenser, FuelProduct, Nozzle, Shift, Tank, check_same_business
from tenants.models import Outlet, TenantOwnedModel

from .calculations import calculate_line

PRICE = {"max_digits": 7, "decimal_places": 2}
MONEY = {"max_digits": 14, "decimal_places": 2}
NON_NEGATIVE = [MinValueValidator(Decimal("0"))]
ZERO = Decimal("0")

# Rupee notes counted in the Money Details box, largest first.
DENOMINATIONS = (2000, 500, 200, 100, 50, 20, 10)


class DailySalesSheet(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="sales_sheets")
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="sales_sheets")
    business_date = models.DateField()
    # Copied from the shift when the card is created, so later changes to the
    # shift's order cannot reshuffle the reading history.
    shift_sort_order = models.PositiveSmallIntegerField()
    dispenser = models.ForeignKey(Dispenser, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="shift_cards", verbose_name="MPD / DU")
    employee = models.ForeignKey("operations.Employee", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="shift_cards", verbose_name="employee (DSM)")
    cashier_name = models.CharField(max_length=100, blank=True)
    helper_name = models.CharField(max_length=100, blank=True)
    tanker_card = models.BooleanField(default=False, help_text="Tick for a tanker / bulk sale card.")
    time_from = models.TimeField(null=True, blank=True)
    time_to = models.TimeField(null=True, blank=True)
    notes = models.CharField("remark", max_length=255, blank=True)

    # --- Money details ---------------------------------------------------------
    general_credit = models.DecimalField("gen. credit sale", **MONEY, default=ZERO, validators=NON_NEGATIVE,
                                         help_text="Credit given to someone who is not a registered credit customer.")
    general_credit_party = models.CharField(max_length=100, blank=True)
    bank_card = models.DecimalField(**MONEY, default=ZERO, validators=NON_NEGATIVE)
    company_card = models.DecimalField(**MONEY, default=ZERO, validators=NON_NEGATIVE,
                                       help_text="Oil-company fleet / loyalty cards.")
    phone_wallet = models.DecimalField("phone wallet (UPI)", **MONEY, default=ZERO, validators=NON_NEGATIVE)
    notes_2000 = models.PositiveIntegerField(default=0)
    notes_500 = models.PositiveIntegerField(default=0)
    notes_200 = models.PositiveIntegerField(default=0)
    notes_100 = models.PositiveIntegerField(default=0)
    notes_50 = models.PositiveIntegerField(default=0)
    notes_20 = models.PositiveIntegerField(default=0)
    notes_10 = models.PositiveIntegerField(default=0)
    coins = models.DecimalField(**MONEY, default=ZERO, validators=NON_NEGATIVE)

    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-business_date", "-shift_sort_order", "pk"]
        verbose_name = "shift card"
        indexes = [models.Index(fields=["business", "business_date"])]

    def __str__(self):
        who = f" {self.employee}" if self.employee_id else ""
        du = f" {self.dispenser}" if self.dispenser_id else ""
        return f"{self.outlet.code} {self.business_date:%d-%m-%Y} {self.shift.name}{du}{who}"

    def get_absolute_url(self):
        return reverse("sales:sheet_detail", args=[self.pk])

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "shift", "dispenser")
        if self.shift_id and self.outlet_id and self.shift.outlet_id != self.outlet_id:
            raise ValidationError({"shift": "This shift belongs to a different outlet."})
        if self.dispenser_id and self.outlet_id and self.dispenser.outlet_id != self.outlet_id:
            raise ValidationError({"dispenser": "This MPD / DU is at a different outlet."})
        if self.employee_id and self.outlet_id and self.employee.outlet_id != self.outlet_id:
            raise ValidationError({"employee": "This employee works at a different outlet."})

    @property
    def cash_collection(self):
        """Cash counted in the Money Details box: notes x denomination + coins."""
        return sum((Decimal(getattr(self, f"notes_{d}")) * d for d in DENOMINATIONS), ZERO) + (self.coins or ZERO)

    def _later_q(self, prefix=""):
        return Q(**{f"{prefix}business_date__gt": self.business_date}) | Q(
            **{f"{prefix}business_date": self.business_date, f"{prefix}shift_sort_order__gt": self.shift_sort_order}
        )

    def has_later_readings(self):
        """True if a later card already starts from this card's closing readings."""
        nozzles = self.lines.values("nozzle")
        return DailySalesLine.objects.filter(nozzle__in=nozzles).filter(self._later_q("sheet__")).exists()


class DailySalesLine(TenantOwnedModel):
    sheet = models.ForeignKey(DailySalesSheet, on_delete=models.CASCADE, related_name="lines")
    nozzle = models.ForeignKey(Nozzle, on_delete=models.PROTECT, related_name="sales_lines")
    product = models.ForeignKey(FuelProduct, on_delete=models.PROTECT, related_name="sales_lines")
    # The tank the nozzle drew from when the card was saved.
    # Empty on lines recorded before tanks were set up.
    tank = models.ForeignKey(Tank, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_lines")

    opening_reading = models.DecimalField(**LITRES, validators=NON_NEGATIVE)
    closing_reading = models.DecimalField(**LITRES, null=True, blank=True, validators=NON_NEGATIVE)
    testing_litres = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"), validators=NON_NEGATIVE,
        help_text="Litres dispensed for delivery testing. Not counted as customer sales.",
    )
    price_per_litre = models.DecimalField(**PRICE)

    meter_reset = models.BooleanField(
        default=False, help_text="Tick only if the meter rolled over or was replaced during this shift."
    )
    reading_before_reset = models.DecimalField(**LITRES, null=True, blank=True, validators=NON_NEGATIVE)
    reading_after_reset = models.DecimalField(**LITRES, null=True, blank=True, validators=NON_NEGATIVE)
    notes = models.CharField(max_length=255, blank=True)

    # Calculated by calculate_line(); empty until a closing reading is entered.
    total_delivery = models.DecimalField(**LITRES, null=True, blank=True, editable=False)
    net_sales_litres = models.DecimalField(**LITRES, null=True, blank=True, editable=False)
    sales_value = models.DecimalField(**MONEY, null=True, blank=True, editable=False)

    class Meta:
        ordering = ["nozzle__code"]
        constraints = [
            models.UniqueConstraint(fields=["sheet", "nozzle"], name="unique_nozzle_per_sales_sheet"),
        ]

    def __str__(self):
        return f"{self.sheet} {self.nozzle.code}"

    def figures(self):
        """Validate the readings and return LineFigures (raises ValidationError)."""
        return calculate_line(
            self.opening_reading, self.closing_reading, self.testing_litres, self.price_per_litre,
            meter_reset=self.meter_reset,
            before_reset=self.reading_before_reset,
            after_reset=self.reading_after_reset,
        )

    @property
    def stock_consumption(self):
        """Fuel that physically left the tank: the total delivery, testing included."""
        return self.total_delivery

    def clean(self):
        super().clean()
        check_same_business(self, "sheet", "nozzle", "product")
        # Nothing to calculate yet, or not a real line.
        if self.closing_reading is None or self.opening_reading is None or self.price_per_litre is None:
            return
        if self.meter_reset and not self.notes.strip():
            raise ValidationError({"notes": "Explain the meter rollover or replacement."})
        try:
            self.figures()
        except ValidationError as error:
            # The price is not entered on the card, so report it as a general error.
            raise ValidationError({
                (NON_FIELD_ERRORS if field == "price_per_litre" else field): messages
                for field, messages in error.message_dict.items()
            })

    def save(self, *args, **kwargs):
        if not self.meter_reset:
            self.reading_before_reset = self.reading_after_reset = None
        if self.closing_reading is None:
            self.total_delivery = self.net_sales_litres = self.sales_value = None
        else:
            result = self.figures()
            self.total_delivery = result.total_delivery
            self.net_sales_litres = result.net_sales_litres
            self.sales_value = result.sales_value
        super().save(*args, **kwargs)


class SalesCorrection(TenantOwnedModel):
    """A correction to an older Shift Card. Applied immediately when saved."""

    class Status(models.TextChoices):
        APPLIED = "APPLIED", "Applied"

    sheet = models.ForeignKey(DailySalesSheet, on_delete=models.CASCADE, related_name="corrections")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.APPLIED)
    reason = models.TextField()
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Correction to {self.sheet}"


class CorrectionLine(TenantOwnedModel):
    """One nozzle's old and new values. Kept permanently as correction history."""

    correction = models.ForeignKey(SalesCorrection, on_delete=models.CASCADE, related_name="lines")
    line = models.ForeignKey(DailySalesLine, on_delete=models.CASCADE, related_name="correction_lines")
    old_closing_reading = models.DecimalField(**LITRES)
    new_closing_reading = models.DecimalField(**LITRES)
    old_testing_litres = models.DecimalField(max_digits=10, decimal_places=2)
    new_testing_litres = models.DecimalField(max_digits=10, decimal_places=2)
    old_price_per_litre = models.DecimalField(**PRICE)
    new_price_per_litre = models.DecimalField(**PRICE)
    # When a closing reading changes, the next card's opening reading for the
    # same nozzle changes with it. Both values are recorded here.
    next_line = models.ForeignKey(
        DailySalesLine, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    next_old_opening = models.DecimalField(**LITRES, null=True, blank=True)
    next_new_opening = models.DecimalField(**LITRES, null=True, blank=True)

    class Meta:
        ordering = ["line__nozzle__code"]

    @property
    def closing_changed(self):
        return self.old_closing_reading != self.new_closing_reading
