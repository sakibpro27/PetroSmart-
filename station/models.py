"""
Outlet equipment, shifts and selling prices (Phase 2).

* FuelProduct - a fuel the business sells, in the MS (petrol) or HSD (diesel) category.
* FuelPrice   - selling price per litre at one outlet, from a given date.
* Dispenser   - a dispensing unit (DU) at an outlet.
* Nozzle      - one nozzle on a dispenser. Daily Sales readings are per nozzle.
* Shift       - a working shift at an outlet, e.g. Morning 06:00-14:00.

Every model is tenant-owned. clean() also checks that linked records belong
to the same business and outlet, so a tampered form can never attach one
dealer's nozzle to another dealer's dispenser.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from tenants.models import Outlet, TenantOwnedModel

# Totalizer readings: up to 9,999,999,999.99 litres.
LITRES = {"max_digits": 12, "decimal_places": 2}


def check_same_business(instance, *field_names):
    errors = {}
    for name in field_names:
        related = getattr(instance, name, None)
        if related is not None and related.business_id != instance.business_id:
            errors[name] = "Select a valid choice."
    if errors:
        raise ValidationError(errors)


class FuelProduct(TenantOwnedModel):
    class Category(models.TextChoices):
        MS = "MS", "MS (Petrol)"
        HSD = "HSD", "HSD (Diesel)"

    category = models.CharField(max_length=3, choices=Category.choices)
    code = models.CharField(max_length=10, help_text="Short code shown on reports, e.g. MS, HSD, XP95.")
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"],
                name="unique_product_code_per_business",
                violation_error_message="A product with this code already exists.",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip().upper()
        if self.pk and not self.is_active and self.nozzles.filter(is_active=True).exists():
            raise ValidationError(
                {"is_active": "Active nozzles still use this product. Deactivate those nozzles first."}
            )


DEFAULT_PRODUCTS = [
    (FuelProduct.Category.MS, "MS", "Petrol (MS)"),
    (FuelProduct.Category.HSD, "HSD", "Diesel (HSD)"),
]


def create_default_products(business):
    """Every business starts with MS and HSD. Safe to call more than once."""
    for category, code, name in DEFAULT_PRODUCTS:
        FuelProduct.objects.get_or_create(
            business=business, code=code, defaults={"category": category, "name": name}
        )


class FuelPrice(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="fuel_prices")
    product = models.ForeignKey(FuelProduct, on_delete=models.PROTECT, related_name="prices")
    effective_from = models.DateField(help_text="The price applies from this date until a newer price starts.")
    price_per_litre = models.DecimalField(
        max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Selling price in ₹ per litre.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "product__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["outlet", "product", "effective_from"],
                name="unique_price_per_outlet_product_date",
                violation_error_message="A price for this product already starts on this date. Edit that price instead.",
            ),
        ]

    def __str__(self):
        return f"{self.product.code} ₹{self.price_per_litre}/L from {self.effective_from:%d-%m-%Y}"

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "product")

    @classmethod
    def price_on(cls, outlet, product, date):
        """The price in force at `outlet` for `product` on `date`, or None."""
        return (
            cls.objects.filter(outlet=outlet, product=product, effective_from__lte=date)
            .order_by("-effective_from")
            .first()
        )


class Dispenser(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="dispensers")
    code = models.CharField(max_length=20, help_text="e.g. DU-1")
    make = models.CharField(max_length=60, blank=True, help_text="Manufacturer and model (optional).")
    serial_number = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["outlet", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["outlet", "code"],
                name="unique_dispenser_code_per_outlet",
                violation_error_message="A dispenser with this code already exists at this outlet.",
            ),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        super().clean()
        check_same_business(self, "outlet")
        if self.pk and not self.is_active and self.nozzles.filter(is_active=True).exists():
            raise ValidationError(
                {"is_active": "This dispenser still has active nozzles. Deactivate them first."}
            )


class VolumeBasis(models.TextChoices):
    """
    How a quantity of fuel was measured. Only observed (ambient) litres are
    supported today. Temperature-corrected volumes can be added later as a
    new choice; stock reconciliation refuses to mix different bases.
    """

    OBSERVED = "OBSERVED", "Observed litres (no temperature correction)"


class Tank(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="tanks")
    product = models.ForeignKey(FuelProduct, on_delete=models.PROTECT, related_name="tanks")
    code = models.CharField(max_length=20, help_text="e.g. T1. Must be unique within the outlet.")
    capacity_litres = models.DecimalField(**LITRES, validators=[MinValueValidator(Decimal("1"))])
    starting_stock = models.DecimalField(
        **LITRES, validators=[MinValueValidator(Decimal("0"))],
        help_text="Litres in the tank at the end of the day before the first stock sheet. "
        "It becomes the first opening stock.",
    )
    variation_alert_litres = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("25.00"), validators=[MinValueValidator(Decimal("0"))],
        help_text="A daily stock variation larger than this is flagged for the Dealer and needs an explanation. "
        "Set it to suit your tank and dip method.",
    )
    volume_basis = models.CharField(max_length=20, choices=VolumeBasis.choices, default=VolumeBasis.OBSERVED,
                                    editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["outlet", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["outlet", "code"],
                name="unique_tank_code_per_outlet",
                violation_error_message="A tank with this code already exists at this outlet.",
            ),
        ]

    def __str__(self):
        return f"{self.code} ({self.product.code})"

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "product")
        if self.capacity_litres is not None and self.starting_stock is not None and self.starting_stock > self.capacity_litres:
            raise ValidationError({"starting_stock": "Starting stock cannot be more than the tank capacity."})
        if self.pk:
            linked = self.nozzles.filter(is_active=True)
            if not self.is_active and linked.exists():
                raise ValidationError({"is_active": "Active nozzles still draw from this tank. Link them elsewhere first."})
            if self.product_id and linked.exclude(product_id=self.product_id).exists():
                raise ValidationError({"product": "Nozzles linked to this tank sell a different product."})


class Nozzle(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="nozzles")
    dispenser = models.ForeignKey(Dispenser, on_delete=models.PROTECT, related_name="nozzles")
    product = models.ForeignKey(FuelProduct, on_delete=models.PROTECT, related_name="nozzles")
    tank = models.ForeignKey(
        Tank, on_delete=models.PROTECT, null=True, blank=True, related_name="nozzles",
        help_text="The tank this nozzle draws from. Needed for tank stock reconciliation.",
    )
    code = models.CharField(max_length=20, help_text="e.g. N1. Must be unique within the outlet.")
    initial_reading = models.DecimalField(
        **LITRES,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Totalizer reading in litres when this nozzle was set up in PetroSmart. "
        "It becomes the first opening reading in Daily Sales.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["outlet", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["outlet", "code"],
                name="unique_nozzle_code_per_outlet",
                violation_error_message="A nozzle with this code already exists at this outlet.",
            ),
        ]

    def __str__(self):
        return f"{self.code} ({self.product.code})"

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "dispenser", "product", "tank")
        errors = {}
        if self.dispenser_id and self.outlet_id and self.dispenser.outlet_id != self.outlet_id:
            errors["dispenser"] = "This dispenser is at a different outlet."
        if self.tank_id:
            if self.outlet_id and self.tank.outlet_id != self.outlet_id:
                errors["tank"] = "This tank is at a different outlet."
            elif self.product_id and self.tank.product_id != self.product_id:
                errors["tank"] = "This tank holds a different product."
            elif self.is_active and not self.tank.is_active:
                errors["tank"] = "This tank is inactive."
        if self.is_active:
            if self.dispenser_id and not self.dispenser.is_active:
                errors["dispenser"] = "This dispenser is inactive."
            if self.product_id and not self.product.is_active:
                errors["product"] = "This product is inactive."
        if errors:
            raise ValidationError(errors)


class Shift(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="shifts")
    name = models.CharField(max_length=40, help_text="e.g. Morning, Evening, Night.")
    start_time = models.TimeField()
    end_time = models.TimeField(help_text="An end time earlier than the start means the shift runs past midnight. "
                                          "The same start and end time means a 24-hour shift.")
    sort_order = models.PositiveSmallIntegerField(default=1, help_text="Order within the day; 1 comes first.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["outlet", "sort_order", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["outlet", "name"],
                name="unique_shift_name_per_outlet",
                violation_error_message="A shift with this name already exists at this outlet.",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}–{self.end_time:%H:%M})"

    @property
    def crosses_midnight(self):
        return self.end_time <= self.start_time

    def clean(self):
        super().clean()
        check_same_business(self, "outlet")
        # Daily Sales sheets are kept in (date, shift order) sequence, so two
        # shifts at one outlet cannot share an order number.
        if self.outlet_id and Shift.objects.filter(outlet_id=self.outlet_id, sort_order=self.sort_order).exclude(pk=self.pk).exists():
            raise ValidationError({"sort_order": "Another shift at this outlet already uses this order number."})
