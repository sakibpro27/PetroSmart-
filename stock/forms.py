from decimal import Decimal

from django import forms
from django.utils import timezone

from core.forms import AuditedModelForm, BootstrapFormMixin
from station.models import Tank
from tenants.models import Outlet

from .models import TankReceipt

DECIMAL_INPUT = {"inputmode": "decimal", "step": "0.01", "min": "0", "autocomplete": "off"}
DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class StockPickForm(BootstrapFormMixin, forms.Form):
    """Outlet and date for a new stock sheet; the tank rows then load."""

    business_date = forms.DateField(label="Business date", widget=DATE_INPUT)
    outlet = forms.ModelChoiceField(queryset=Outlet.objects.none())

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["business_date"].initial = timezone.localdate()
        self.fields["business_date"].widget.attrs["max"] = timezone.localdate().isoformat()
        self.fields["outlet"].queryset = user.accessible_outlets()


class TankRowForm(BootstrapFormMixin, forms.Form):
    tank_id = forms.IntegerField(widget=forms.HiddenInput)
    measured_closing = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"),
                                          label="Measured closing stock (L)")
    notes = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["measured_closing"].widget.attrs.update({**DECIMAL_INPUT, "data-role": "measured"})
        self.fields["notes"].widget.attrs["placeholder"] = "Explain any large variation"


TankRowFormSet = forms.formset_factory(TankRowForm, extra=0)


class StockNotesForm(BootstrapFormMixin, forms.Form):
    notes = forms.CharField(required=False, label="Notes (optional)", widget=forms.Textarea(attrs={"rows": 2}))


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
