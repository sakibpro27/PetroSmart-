"""
Fuel purchases (Phase 5).

* Supplier      - oil company depot or other fuel supplier ("company name").
* FuelPurchase  - one supplier invoice delivered to one outlet.
* PurchaseLine  - one row of the invoice: a product unloaded into one tank,
                  with quantity (KL), rate per KL, delivery charges, VAT,
                  cess and TCS as printed. MS and HSD can share an invoice.
                  Each line creates a stock.TankReceipt for the litres
                  actually unloaded, which is how tank stock reconciliation
                  picks the delivery up.

Line total     = quantity (KL) x rate per KL + delivery charges + VAT + cess + TCS
Invoice amount = sum of line totals + round off

VAT, cess and TCS are typed in as printed on the invoice; PetroSmart does not
calculate taxes.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from station.models import LITRES, FuelProduct, Tank, check_same_business
from tenants.models import Outlet, TenantOwnedModel

MONEY = {"max_digits": 14, "decimal_places": 2}
NON_NEGATIVE = [MinValueValidator(Decimal("0"))]
PAISE = Decimal("0.01")
ZERO = Decimal("0")


class Supplier(TenantOwnedModel):
    name = models.CharField(max_length=150, help_text="e.g. IOCL Terminal, Loni")
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField("GSTIN", max_length=15, blank=True, help_text="Optional. Stored for reference only.")
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "name"],
                name="unique_supplier_name_per_business",
                violation_error_message="A supplier with this name already exists.",
            ),
        ]

    def __str__(self):
        return self.name


class FuelPurchase(TenantOwnedModel):
    outlet = models.ForeignKey(Outlet, on_delete=models.PROTECT, related_name="fuel_purchases")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases",
                                 verbose_name="company name")
    invoice_number = models.CharField("invoice no.", max_length=50)
    invoice_date = models.DateField()
    delivery_date = models.DateField(help_text="The day the fuel was unloaded into the tanks.")
    tanker_number = models.CharField("vehicle no.", max_length=30, blank=True,
                                     help_text="Lorry / tanker registration number.")
    round_up = models.BooleanField(default=False, help_text="Round the invoice total to the nearest rupee.")
    # Both calculated by purchases.services.save_purchase() from the lines, never typed in.
    round_off = models.DecimalField(**MONEY, default=ZERO, editable=False)
    invoice_amount = models.DecimalField(**MONEY, validators=NON_NEGATIVE, editable=False,
                                         help_text="Sum of the line totals plus round off (₹).")
    notes = models.TextField("remark", blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-delivery_date", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "supplier", "invoice_number"],
                name="unique_invoice_per_supplier",
                violation_error_message="This supplier's invoice number is already recorded.",
            ),
        ]

    def __str__(self):
        return f"Invoice {self.invoice_number} ({self.outlet.code})"

    def get_absolute_url(self):
        return reverse("purchases:purchase_detail", args=[self.pk])

    def clean(self):
        super().clean()
        check_same_business(self, "outlet", "supplier")

    def _sum(self, name):
        return sum((getattr(line, name) for line in self.lines.all()), ZERO)

    @property
    def base_amount(self):
        """Quantity x rate on every line, rounded to paise."""
        return self._sum("base_amount")

    @property
    def lines_total(self):
        return self._sum("total")

    @property
    def total_invoiced_litres(self):
        return self._sum("invoiced_litres")

    @property
    def total_received_litres(self):
        return self._sum("received")

    @property
    def product_codes(self):
        return ", ".join(dict.fromkeys(line.product.code for line in self.lines.all()))


def round_off_for(total, round_up):
    """Round off to the nearest rupee, half up: 5,574.40 gives -0.40 and 5,574.50 gives +0.50."""
    if not round_up:
        return ZERO
    return total.quantize(Decimal("1"), rounding=ROUND_HALF_UP) - total


class PurchaseLine(TenantOwnedModel):
    """One row of the invoice, e.g. HSD 12 KL at ₹88,450.00 per KL into tank T1."""

    purchase = models.ForeignKey(FuelPurchase, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(FuelProduct, on_delete=models.PROTECT, related_name="purchase_lines",
                                verbose_name="item name")
    tank = models.ForeignKey(Tank, on_delete=models.PROTECT, related_name="purchase_lines")
    invoiced_litres = models.DecimalField(**LITRES, validators=[MinValueValidator(PAISE)],
                                          help_text="Quantity printed on the invoice, in litres (KL x 1,000).")
    rate_per_kl = models.DecimalField("rate (₹ per KL)", max_digits=12, decimal_places=2,
                                      validators=[MinValueValidator(PAISE)])
    delivery_charges = models.DecimalField("dly taxable charges", **MONEY, default=ZERO, validators=NON_NEGATIVE)
    vat = models.DecimalField("VAT", **MONEY, default=ZERO, validators=NON_NEGATIVE)
    cess = models.DecimalField(**MONEY, default=ZERO, validators=NON_NEGATIVE)
    tcs = models.DecimalField("TCS", **MONEY, default=ZERO, validators=NON_NEGATIVE)
    received_litres = models.DecimalField(
        **LITRES, null=True, blank=True, validators=[MinValueValidator(PAISE)],
        help_text="Litres actually unloaded into the tank. Empty means the same as the invoice.")

    class Meta:
        ordering = ["pk"]  # as entered on the invoice
        constraints = [models.UniqueConstraint(fields=["purchase", "tank"], name="unique_tank_per_purchase")]

    def __str__(self):
        return f"{self.product.code} {self.quantity_kl} KL @ {self.rate_per_kl} into {self.tank.code}"

    def clean(self):
        super().clean()
        check_same_business(self, "product", "tank")
        if self.tank_id and self.product_id and self.tank.product_id != self.product_id:
            raise ValidationError({"tank": f"Tank {self.tank.code} holds {self.tank.product.name}."})

    @property
    def quantity_kl(self):
        return (self.invoiced_litres / 1000).quantize(Decimal("0.001"))

    @property
    def base_amount(self):
        """Quantity (KL) x rate per KL, rounded to paise."""
        return (self.invoiced_litres * self.rate_per_kl / 1000).quantize(PAISE, rounding=ROUND_HALF_UP)

    @property
    def total(self):
        return self.base_amount + self.delivery_charges + self.vat + self.cess + self.tcs

    @property
    def received(self):
        return self.invoiced_litres if self.received_litres is None else self.received_litres

    @property
    def difference(self):
        """Received - invoiced litres. Negative is a shortage."""
        return self.received - self.invoiced_litres
