from django import forms
from django.utils import timezone

from core.forms import AuditedModelForm, BootstrapFormMixin
from station.models import Tank
from tenants.models import Outlet

from .models import StockLine, StockSheet, TankReceipt

DECIMAL_INPUT = {"inputmode": "decimal", "step": "0.01", "min": "0", "autocomplete": "off"}
DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class NewStockSheetForm(BootstrapFormMixin, forms.Form):
    business_date = forms.DateField(label="Business date", widget=DATE_INPUT)
    outlet = forms.ModelChoiceField(queryset=Outlet.objects.none())

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["business_date"].initial = timezone.localdate()
        self.fields["business_date"].widget.attrs["max"] = timezone.localdate().isoformat()
        self.fields["outlet"].queryset = user.accessible_outlets()


class StockLineForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StockLine
        fields = ["measured_closing", "notes"]
        labels = {"measured_closing": "Measured closing stock (L)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["measured_closing"].widget.attrs.update({**DECIMAL_INPUT, "data-role": "measured"})
        self.fields["notes"].widget.attrs["placeholder"] = "Explain any large variation"


StockLineFormSet = forms.modelformset_factory(StockLine, form=StockLineForm, extra=0, edit_only=True)


class StockNotesForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StockSheet
        fields = ["notes"]
        labels = {"notes": "Notes for the Dealer (optional)"}
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class TankChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, tank):
        return f"{tank.outlet.code} · {tank.code} ({tank.product.name})"


class ReceiptForm(AuditedModelForm):
    tank = TankChoiceField(queryset=Tank.objects.none())

    class Meta:
        model = TankReceipt
        fields = ["tank", "received_on", "litres", "reference", "notes"]
        labels = {"received_on": "Received on", "litres": "Litres received (L)"}
        widgets = {"received_on": DATE_INPUT}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.business = user.business
        self.fields["tank"].queryset = (
            Tank.objects.for_business(user.business)
            .filter(outlet__in=user.accessible_outlets(), is_active=True)
            .select_related("outlet", "product")
        )
        self.fields["received_on"].initial = timezone.localdate()
        self.fields["received_on"].widget.attrs["max"] = timezone.localdate().isoformat()
        self.fields["litres"].widget.attrs.update({**DECIMAL_INPUT, "min": "0.01"})

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("tank"):
            self.instance.outlet = cleaned["tank"].outlet  # so the model's own checks can run
        return cleaned
