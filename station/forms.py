from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from core.forms import AuditedModelForm, TenantModelForm
from tenants.models import Business, Outlet

from .models import Dispenser, FuelPrice, FuelProduct, Nozzle, Shift, Tank


class BusinessProfileForm(AuditedModelForm):
    """Contact details the Dealer may change. Plan, status and dates are platform-only."""

    class Meta:
        model = Business
        fields = ["name", "legal_name", "contact_phone", "contact_email", "address"]
        labels = {"name": "Business name", "legal_name": "Registered (legal) name"}
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class OutletForm(TenantModelForm):
    class Meta:
        model = Outlet
        fields = ["name", "code", "oil_company", "address", "gstin", "phone", "email", "bill_terms", "is_active"]
        labels = {"is_active": "Outlet active"}
        widgets = {"address": forms.Textarea(attrs={"rows": 3}), "bill_terms": forms.Textarea(attrs={
            "rows": 4, "placeholder": "Goods once sold will not be taken back.\nPayment within 15 days."})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._was_active = bool(self.instance.pk and self.instance.is_active)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_active") and not self._was_active:
            plan = self.business.plan
            active = Outlet.objects.for_business(self.business).filter(is_active=True).count()
            if active >= plan.max_outlets:
                raise ValidationError(
                    f"Your {plan.name} plan allows {plan.max_outlets} active outlet(s). "
                    "Deactivate an outlet or upgrade your plan."
                )
        return cleaned


class FuelProductForm(TenantModelForm):
    class Meta:
        model = FuelProduct
        fields = ["category", "code", "name", "is_active"]
        labels = {"is_active": "Product active"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # Reports group sales by these, so they are fixed once created.
            for name in ("category", "code"):
                self.fields[name].disabled = True
                self.fields[name].help_text = "Cannot be changed after the product is created."


class DispenserForm(TenantModelForm):
    class Meta:
        model = Dispenser
        fields = ["code", "make", "serial_number", "is_active"]
        labels = {"is_active": "Dispenser active"}


class TankForm(TenantModelForm):
    class Meta:
        model = Tank
        fields = ["code", "product", "capacity_litres", "starting_stock", "variation_alert_litres", "is_active"]
        labels = {
            "capacity_litres": "Capacity (L)",
            "starting_stock": "Starting stock (L)",
            "variation_alert_litres": "Variation alert limit (L)",
            "is_active": "Tank active",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = Q(pk=self.instance.product_id) if self.instance.product_id else Q(pk__in=[])
        self.fields["product"].queryset = FuelProduct.objects.for_business(self.business).filter(
            Q(is_active=True) | current
        )
        for name in ("capacity_litres", "starting_stock", "variation_alert_litres"):
            self.fields[name].widget.attrs.update({"min": "0", "inputmode": "decimal"})


class NozzleForm(TenantModelForm):
    class Meta:
        model = Nozzle
        fields = ["code", "dispenser", "product", "tank", "initial_reading", "is_active"]
        labels = {"initial_reading": "Starting totalizer reading (L)", "is_active": "Nozzle active"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only this outlet's dispensers and this business's products can be chosen.
        current_dispenser = Q(pk=self.instance.dispenser_id) if self.instance.dispenser_id else Q(pk__in=[])
        current_product = Q(pk=self.instance.product_id) if self.instance.product_id else Q(pk__in=[])
        self.fields["dispenser"].queryset = Dispenser.objects.for_business(self.business).filter(
            Q(outlet=self.outlet, is_active=True) | current_dispenser
        )
        self.fields["product"].queryset = FuelProduct.objects.for_business(self.business).filter(
            Q(is_active=True) | current_product
        )
        current_tank = Q(pk=self.instance.tank_id) if self.instance.tank_id else Q(pk__in=[])
        self.fields["tank"].queryset = Tank.objects.for_business(self.business).filter(
            Q(outlet=self.outlet, is_active=True) | current_tank
        ).select_related("product")
        self.fields["initial_reading"].widget.attrs.update({"min": "0", "inputmode": "decimal"})


class ShiftForm(TenantModelForm):
    class Meta:
        model = Shift
        fields = ["name", "start_time", "end_time", "sort_order", "is_active"]
        labels = {"is_active": "Shift active"}
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }


class FuelPriceForm(TenantModelForm):
    class Meta:
        model = FuelPrice
        fields = ["product", "effective_from", "price_per_litre"]
        labels = {"price_per_litre": "Selling price (₹ per litre)"}
        widgets = {"effective_from": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = Q(pk=self.instance.product_id) if self.instance.product_id else Q(pk__in=[])
        self.fields["product"].queryset = FuelProduct.objects.for_business(self.business).filter(
            Q(is_active=True) | current
        )
        self.fields["price_per_litre"].widget.attrs.update({"min": "0.01", "inputmode": "decimal"})
