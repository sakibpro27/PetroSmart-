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
        fields = ["outlet", "supplier", "invoice_number", "invoice_date", "delivery_date",
                  "invoice_amount", "tanker_number", "notes"]
        labels = {"invoice_amount": "Invoice amount (₹)"}
        widgets = {"invoice_date": DATE_INPUT, "delivery_date": DATE_INPUT, "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = user.business
        self.instance.business = user.business
        today = timezone.localdate()
        self.fields["outlet"].queryset = user.accessible_outlets()
        current_supplier = Q(pk=self.instance.supplier_id) if self.instance.supplier_id else Q(pk__in=[])
        self.fields["supplier"].queryset = Supplier.objects.for_business(user.business).filter(Q(is_active=True) | current_supplier)
        for name in ("invoice_date", "delivery_date"):
            self.fields[name].initial = today
            self.fields[name].widget.attrs["max"] = today.isoformat()
        self.fields["invoice_amount"].widget.attrs.update({**DECIMAL_INPUT})

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


class ProductLineForm(BootstrapFormMixin, forms.Form):
    """One product on the invoice. Leave a row empty if that product is not on this invoice."""

    product = forms.ModelChoiceField(queryset=FuelProduct.objects.none(), required=False)
    invoiced_litres = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False,
                                         label="Invoiced quantity (L)")
    purchase_rate = forms.DecimalField(max_digits=9, decimal_places=4, min_value=Decimal("0.0001"), required=False,
                                       label="Rate (₹ per litre)")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = FuelProduct.objects.for_business(user.business).filter(is_active=True)
        self.fields["invoiced_litres"].widget.attrs.update({**DECIMAL_INPUT, "min": "0.01"})
        self.fields["purchase_rate"].widget.attrs.update({**DECIMAL_INPUT, "step": "0.0001"})

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("invoiced_litres") and not cleaned.get("purchase_rate"):
            # Quantity and rate left blank: this product is not on the invoice.
            cleaned["product"] = None
            return cleaned
        if not all(cleaned.get(name) for name in ("product", "invoiced_litres", "purchase_rate")):
            raise forms.ValidationError("Fill in the product, quantity and rate, or leave quantity and rate empty.")
        return cleaned


# Two rows by default so MS and HSD on the same invoice can be entered together.
ProductLineFormSet = forms.formset_factory(ProductLineForm, extra=0, min_num=2, max_num=10, validate_max=True)


class AllocationForm(BootstrapFormMixin, forms.Form):
    """Litres unloaded into one tank."""

    tank = TankChoiceField(queryset=Tank.objects.none(), required=False)
    litres = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False,
                                label="Litres received (L)")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tank"].queryset = (
            Tank.objects.for_business(user.business).filter(outlet__in=user.accessible_outlets(), is_active=True)
            .select_related("outlet", "product")
        )
        self.fields["litres"].widget.attrs.update({**DECIMAL_INPUT, "min": "0.01"})

    def clean(self):
        cleaned = super().clean()
        if bool(cleaned.get("tank")) != bool(cleaned.get("litres")):
            raise forms.ValidationError("Choose a tank and enter the litres, or leave both empty.")
        return cleaned


# One blank row is always shown so a delivery split across tanks can be entered.
AllocationFormSet = forms.formset_factory(AllocationForm, extra=1, max_num=10, validate_max=True)


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
