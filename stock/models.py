"""
Tank stock (Phase 4).

* TankReceipt - fuel unloaded into a tank (tanker delivery). Phase 5 links
                these to purchase invoices.
* StockSheet  - one outlet, one business date. Draft -> Submitted -> Approved.
* StockLine   - one tank on that sheet: opening stock, fuel received, total
                nozzle delivery (with testing litres shown as part of it),
                calculated closing, measured dip closing and the variation.

Opening stock is the previous day's MEASURED closing stock, so each day's
variation stands on its own instead of being carried forward.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from station.models import LITRES, FuelProduct, Tank, VolumeBasis, check_same_business
from tenants.models import Outlet, TenantOwnedModel

from .calculations import reconcile


class TankReceipt(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="tank_receipts")
    tank = models.ForeignKey(Tank, on_delete=models.PROTECT, related_name="receipts")
    received_on = models.DateField()
    litres = models.DecimalField(**LITRES, validators=[MinValueValidator(Decimal("0.01"))],
                                 help_text="Litres unloaded into this tank, as measured at the outlet.")
    reference = models.CharField(max_length=60, blank=True, help_text="Challan, invoice or tanker number.")
    notes = models.CharField(max_length=255, blank=True)
    volume_basis = models.CharField(max_length=20, choices=VolumeBasis.choices, default=VolumeBasis.OBSERVED,
                                    editable=False)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when the receipt is part of a supplier invoice (Phase 5). Receipts
    # without a purchase are still allowed, e.g. a transfer from another outlet.
    purchase = models.ForeignKey("purchases.FuelPurchase", on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="receipts")

    class Meta:
        ordering = ["-received_on", "-pk"]

    def __str__(self):
        return f"{self.litres} L into {self.tank.code} on {self.received_on:%d-%m-%Y}"

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "tank")
        if self.tank_id and self.outlet_id and self.tank.outlet_id != self.outlet_id:
            raise ValidationError({"tank": "This tank is at a different outlet."})


class StockSheet(TenantOwnedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Awaiting approval"
        APPROVED = "APPROVED", "Approved"

    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="stock_sheets")
    business_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-business_date", "outlet__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["outlet", "business_date"],
                name="unique_stock_sheet_per_outlet_date",
                violation_error_message="A stock sheet already exists for this outlet and date.",
            ),
        ]

    def __str__(self):
        return f"{self.outlet.code} stock {self.business_date:%d-%m-%Y}"

    def get_absolute_url(self):
        return reverse("stock:sheet_detail", args=[self.pk])

    @property
    def is_latest(self):
        return not StockSheet.objects.filter(outlet=self.outlet, business_date__gt=self.business_date).exists()


class StockLine(TenantOwnedModel):
    sheet = models.ForeignKey(StockSheet, on_delete=models.PROTECT, related_name="lines")
    tank = models.ForeignKey(Tank, on_delete=models.PROTECT, related_name="stock_lines")
    product = models.ForeignKey(FuelProduct, on_delete=models.PROTECT, related_name="+")

    opening_stock = models.DecimalField(**LITRES)
    fuel_received = models.DecimalField(**LITRES, default=Decimal("0"))
    total_delivery = models.DecimalField(**LITRES, default=Decimal("0"),
                                         help_text="All fuel dispensed from this tank's nozzles, testing litres included.")
    testing_litres = models.DecimalField(**LITRES, default=Decimal("0"),
                                         help_text="Shown for information only. Already part of the total delivery.")
    calculated_closing = models.DecimalField(**LITRES, editable=False)
    measured_closing = models.DecimalField(**LITRES, null=True, blank=True,
                                           validators=[MinValueValidator(Decimal("0"))])
    variation = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, editable=False)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["tank__code"]
        constraints = [models.UniqueConstraint(fields=["sheet", "tank"], name="unique_tank_per_stock_sheet")]

    def __str__(self):
        return f"{self.sheet} {self.tank.code}"

    @property
    def is_flagged(self):
        """True when the variation is beyond the tank's alert limit."""
        return self.variation is not None and abs(self.variation) > self.tank.variation_alert_litres

    def clean(self):
        super().clean()
        if self.measured_closing is None or self.opening_stock is None:
            return
        if self.measured_closing > self.tank.capacity_litres:
            raise ValidationError({"measured_closing": f"Cannot be more than the tank capacity ({self.tank.capacity_litres} L)."})
        figures = reconcile(self.opening_stock, self.fuel_received, self.total_delivery, self.measured_closing)
        if abs(figures.variation) > self.tank.variation_alert_litres and not self.notes.strip():
            raise ValidationError({"notes": (
                f"The variation of {figures.variation} L is beyond this tank's alert limit "
                f"of {self.tank.variation_alert_litres} L. Explain it here."
            )})

    def save(self, *args, **kwargs):
        figures = reconcile(self.opening_stock, self.fuel_received, self.total_delivery, self.measured_closing)
        self.calculated_closing = figures.calculated_closing
        self.variation = figures.variation
        super().save(*args, **kwargs)
