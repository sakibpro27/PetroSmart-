"""
Fuel purchases (Phase 5).

* Supplier      - oil company depot or other fuel supplier.
* FuelPurchase  - one supplier invoice delivered to one outlet.
* PurchaseLine  - one product on the invoice (MS and HSD can share an invoice).
                  The litres actually unloaded go into tanks as
                  stock.TankReceipt rows linked to the purchase, which is how
                  tank stock reconciliation picks them up.

The invoice amount is recorded as printed on the invoice. PetroSmart does not
calculate taxes; any difference from quantity x rate is shown as
"other charges / taxes" for information only.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from station.models import LITRES, FuelProduct, check_same_business
from tenants.models import Outlet, TenantOwnedModel


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
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases")
    invoice_number = models.CharField(max_length=50)
    invoice_date = models.DateField()
    delivery_date = models.DateField(help_text="The day the fuel was unloaded into the tanks.")
    invoice_amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0"))],
                                         help_text="Total payable as printed on the invoice (₹).")
    tanker_number = models.CharField(max_length=30, blank=True, help_text="Lorry / tanker registration number.")
    notes = models.TextField(blank=True)
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

    @property
    def base_amount(self):
        """Invoiced litres x rate on every product line, rounded to paise."""
        return sum((line.base_amount for line in self.lines.all()), Decimal("0"))

    @property
    def other_charges(self):
        """Invoice amount minus litres x rate: taxes, freight or other charges on the invoice."""
        return self.invoice_amount - self.base_amount

    @property
    def total_invoiced_litres(self):
        return sum((line.invoiced_litres for line in self.lines.all()), Decimal("0"))

    @property
    def product_codes(self):
        return ", ".join(line.product.code for line in self.lines.all())


class PurchaseLine(TenantOwnedModel):
    """One product on an invoice, e.g. MS 12,000 L at ₹94.50 and HSD 8,000 L at ₹87.20."""

    purchase = models.ForeignKey(FuelPurchase, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(FuelProduct, on_delete=models.PROTECT, related_name="purchase_lines")
    invoiced_litres = models.DecimalField(**LITRES, validators=[MinValueValidator(Decimal("0.01"))],
                                          help_text="Quantity printed on the invoice.")
    purchase_rate = models.DecimalField(max_digits=9, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))],
                                        help_text="Rate per litre on the invoice (₹).")

    class Meta:
        ordering = ["-product__category", "product__code"]  # MS (petrol) first, then HSD
        constraints = [models.UniqueConstraint(fields=["purchase", "product"], name="unique_product_per_purchase")]

    def __str__(self):
        return f"{self.product.code} {self.invoiced_litres} L @ {self.purchase_rate}"

    @property
    def base_amount(self):
        return (self.invoiced_litres * self.purchase_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
