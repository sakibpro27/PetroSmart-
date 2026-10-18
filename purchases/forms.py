from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from core.forms import AuditedModelForm, BootstrapFormMixin, TenantModelForm
from station.models import FuelProduct, Tank
from stock.forms import DATE_INPUT, DECIMAL_INPUT, TankChoiceField

from .models import FuelPurchase, Supplier


class SupplierForm(TenantModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "phone", "email", "gstin", "address", "is_active"]
        labels = {"is_active": "Supplier active"}
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class PurchaseForm(AuditedModelForm):
    class Meta:
        model = FuelPurchase
        fields = ["outlet", "supplier", "invoice_number", "invoice_date", "delivery_date", "tanker_number",
                  "round_up", "notes"]
        widgets = {"invoice_date": DATE_INPUT, "delivery_date": DATE_INPUT,
                   "notes": forms.TextInput(attrs={"placeholder": "Remark"})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = user.business
        self.instance.business = user.business
        today = timezone.localdate()
        self.fields["outlet"].queryset = user.accessible_outlets()
        if self.fields["outlet"].queryset.count() == 1 and not self.instance.pk:
            self.fields["outlet"].initial = self.fields["outlet"].queryset.get()
        current_supplier = Q(pk=self.instance.supplier_id) if self.instance.supplier_id else Q(pk__in=[])
        self.fields["supplier"].queryset = Supplier.objects.for_business(user.business).filter(Q(is_active=True) | current_supplier)
        for name in ("invoice_date", "delivery_date"):
            self.fields[name].initial = today
            self.fields[name].widget.attrs["max"] = today.isoformat()
        self.fields["outlet"].widget.attrs["data-purchase-outlet"] = "1"
        self.fields["round_up"].widget.attrs["data-round-up"] = "1"

    def _get_validation_exclusions(self):
        # Check "invoice number unique per supplier" with a friendly message.
        exclude = super()._get_validation_exclusions()
        exclude.discard("business")
        return exclude

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("invoice_date") and cleaned.get("delivery_date") and cleaned["delivery_date"] < cleaned["invoice_date"]:
            self.add_error("delivery_date", "Delivery cannot be before the invoice date.")
        return cleaned


MONEY_FIELD = {"max_digits": 14, "decimal_places": 2, "min_value": Decimal("0"), "required": False}


class PurchaseLineForm(BootstrapFormMixin, forms.Form):
    """
    One row of the invoice table. A row left completely empty is skipped.
    Quantity is entered in KL (as on the invoice) and stored in litres.
    """

    product = forms.ModelChoiceField(queryset=FuelProduct.objects.none(), required=False, label="Item name")
    quantity_kl = forms.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"), required=False,
                                     label="Quantity (KL)")
    rate_per_kl = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False,
                                     label="Rate (₹/KL)")
    delivery_charges = forms.DecimalField(label="Dly taxable charges", **MONEY_FIELD)
    vat = forms.DecimalField(label="VAT", **MONEY_FIELD)
    cess = forms.DecimalField(label="Cess", **MONEY_FIELD)
    tcs = forms.DecimalField(label="TCS", **MONEY_FIELD)
    tank = TankChoiceField(queryset=Tank.objects.none(), required=False)
    received_litres = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False,
                                         label="Litres actually received",
                                         help_text="Only if the dip after unloading differs from the invoice.")

    AMOUNTS = ("delivery_charges", "vat", "cess", "tcs")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.empty_permitted = True
        self.use_required_attribute = False
        self.fields["product"].queryset = FuelProduct.objects.for_business(user.business).filter(is_active=True)
        self.fields["tank"].queryset = (
            Tank.objects.for_business(user.business).filter(outlet__in=user.accessible_outlets(), is_active=True)
            .select_related("outlet", "product")
        )
        self.fields["quantity_kl"].widget.attrs.update({**DECIMAL_INPUT, "step": "0.001", "data-kl": "1"})
        self.fields["rate_per_kl"].widget.attrs.update({**DECIMAL_INPUT, "data-rate": "1"})
        for name in self.AMOUNTS:
            self.fields[name].widget.attrs.update({**DECIMAL_INPUT, "data-charge": "1", "placeholder": "0"})
        self.fields["received_litres"].widget.attrs.update({**DECIMAL_INPUT, "min": "0.01"})
        self.fields["product"].widget.attrs["data-line-product"] = "1"
        self.fields["tank"].widget.attrs["data-line-tank"] = "1"

    def clean(self):
        cleaned = super().clean()
        typed = [cleaned.get(name) for name in ("quantity_kl", "rate_per_kl", "received_litres", *self.AMOUNTS)]
        if not any(value not in (None, "") for value in typed):
            cleaned["product"] = None  # quantity, rate and charges all empty: not on this invoice
            return cleaned
        missing = [self[name].label for name in ("product", "quantity_kl", "rate_per_kl", "tank")
                   if not cleaned.get(name)]
        if missing:
            raise forms.ValidationError(f"Fill in {', '.join(missing)}, or clear the row.")
        tank, product = cleaned["tank"], cleaned["product"]
        if tank.product_id != product.pk:
            self.add_error("tank", f"Tank {tank.code} holds {tank.product.name}, not {product.name}.")
        for name in self.AMOUNTS:
            cleaned[name] = cleaned.get(name) or Decimal("0")
        return cleaned

    def line_values(self):
        """The row as PurchaseLine field values, or None for an empty row."""
        data = self.cleaned_data
        if not data.get("product"):
            return None
        return {"product": data["product"], "tank": data["tank"], "invoiced_litres": data["quantity_kl"] * 1000,
                "rate_per_kl": data["rate_per_kl"], "received_litres": data.get("received_litres"),
                **{name: data[name] for name in self.AMOUNTS}}


# One row per product by default (MS and HSD on the same invoice); "Add new" adds more.
PurchaseLineFormSet = forms.formset_factory(PurchaseLineForm, extra=0, max_num=20, validate_max=True)


class PurchaseFilterForm(BootstrapFormMixin, forms.Form):
    date_from = forms.DateField(label="Delivered from", required=False, widget=DATE_INPUT)
    date_to = forms.DateField(label="to", required=False, widget=DATE_INPUT)
    outlet = forms.ModelChoiceField(queryset=None, required=False, empty_label="All outlets")
    product = forms.ModelChoiceField(queryset=None, required=False, empty_label="All products")
    supplier = forms.ModelChoiceField(queryset=None, required=False, empty_label="All suppliers")

    def __init__(self, *args, user, outlets, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["outlet"].queryset = outlets
        self.fields["product"].queryset = FuelProduct.objects.for_business(user.business)
        self.fields["supplier"].queryset = Supplier.objects.for_business(user.business)
