from datetime import date
from decimal import Decimal

from django import forms
from django.utils import timezone

from core.forms import BootstrapFormMixin
from station.models import FuelProduct, Shift

from .models import DailySalesLine, DailySalesSheet
from .reports import GROUPINGS
from .services import viewable_outlets


class ShiftChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, shift):
        return f"{shift.outlet.code} · {shift.name} ({shift.start_time:%H:%M}–{shift.end_time:%H:%M})"


class NewSheetForm(BootstrapFormMixin, forms.Form):
    business_date = forms.DateField(
        label="Business date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    shift = ShiftChoiceField(queryset=Shift.objects.none(), label="Outlet and shift")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["business_date"].initial = timezone.localdate()
        self.fields["business_date"].widget.attrs["max"] = timezone.localdate().isoformat()
        # Only shifts at outlets this user works at.
        self.fields["shift"].queryset = (
            Shift.objects.for_business(user.business)
            .filter(outlet__in=user.accessible_outlets(), is_active=True)
            .select_related("outlet")
            .order_by("outlet__code", "sort_order")
        )


DECIMAL_INPUT = {"inputmode": "decimal", "step": "0.01", "min": "0", "autocomplete": "off"}


class LineEntryForm(BootstrapFormMixin, forms.ModelForm):
    """One nozzle row. Opening reading and price are shown but never accepted from the browser."""

    class Meta:
        model = DailySalesLine
        fields = ["closing_reading", "testing_litres", "meter_reset", "reading_before_reset", "reading_after_reset", "notes"]
        labels = {
            "closing_reading": "Closing reading (L)",
            "testing_litres": "Testing litres (L)",
            "meter_reset": "Meter rolled over or replaced during this shift",
            "reading_before_reset": "Last reading before reset (L)",
            "reading_after_reset": "First reading after reset (L)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("closing_reading", "testing_litres", "reading_before_reset", "reading_after_reset"):
            self.fields[name].widget.attrs.update(DECIMAL_INPUT)
        self.fields["closing_reading"].widget.attrs["data-role"] = "closing"
        self.fields["testing_litres"].widget.attrs["data-role"] = "testing"
        self.fields["meter_reset"].widget.attrs["data-role"] = "reset"
        self.fields["reading_before_reset"].widget.attrs["data-role"] = "before"
        self.fields["reading_after_reset"].widget.attrs["data-role"] = "after"
        self.fields["notes"].widget.attrs["placeholder"] = "Notes (required for a meter reset)"


LineFormSet = forms.modelformset_factory(DailySalesLine, form=LineEntryForm, extra=0, edit_only=True)


class SheetNotesForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = DailySalesSheet
        fields = ["notes"]
        labels = {"notes": "Notes for the Dealer (optional)"}
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class ReviewNoteForm(BootstrapFormMixin, forms.Form):
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), max_length=1000)


class CorrectionRequestForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), max_length=1000,
        help_text="Explain why the approved figures are wrong. The Dealer sees this before approving.",
    )

    def __init__(self, *args, sheet, **kwargs):
        super().__init__(*args, **kwargs)
        self.lines = list(sheet.lines.select_related("nozzle", "product"))
        for line in self.lines:
            for key, initial, digits, minimum in (
                ("closing", line.closing_reading, 12, Decimal("0")),
                ("testing", line.testing_litres, 10, Decimal("0")),
                ("price", line.price_per_litre, 7, Decimal("0.01")),
            ):
                field = forms.DecimalField(max_digits=digits, decimal_places=2, min_value=minimum, initial=initial)
                field.widget.attrs.update({**DECIMAL_INPUT, "min": str(minimum), "class": "form-control form-control-sm"})
                self.fields[f"{key}_{line.pk}"] = field

    def rows(self):
        for line in self.lines:
            yield line, self[f"closing_{line.pk}"], self[f"testing_{line.pk}"], self[f"price_{line.pk}"]

    def clean(self):
        cleaned = super().clean()
        self.changes = []
        for line in self.lines:
            values = [cleaned.get(f"{key}_{line.pk}") for key in ("closing", "testing", "price")]
            if None in values:
                continue  # that field already has its own error
            if tuple(values) != (line.closing_reading, line.testing_litres, line.price_per_litre):
                self.changes.append((line, *values))
        if not self.errors and not self.changes:
            raise forms.ValidationError("Change at least one value, or cancel.")
        return cleaned


class SummaryFilterForm(BootstrapFormMixin, forms.Form):
    group_by = forms.ChoiceField(choices=[(key, label) for key, (label, _) in GROUPINGS.items()], initial="day", label="Group by")
    date_from = forms.DateField(label="From", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    date_to = forms.DateField(label="To", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    outlet = forms.ModelChoiceField(queryset=None, required=False, empty_label="All outlets")
    product = forms.ModelChoiceField(queryset=None, required=False, empty_label="All products")
    include_submitted = forms.BooleanField(required=False, label="Include sheets awaiting approval")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["date_from"].initial = date(today.year, today.month, 1)
        self.fields["date_to"].initial = today
        self.fields["outlet"].queryset = viewable_outlets(user)
        self.fields["product"].queryset = FuelProduct.objects.for_business(user.business)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("date_from") and cleaned.get("date_to") and cleaned["date_from"] > cleaned["date_to"]:
            self.add_error("date_to", "The end date must be on or after the start date.")
        return cleaned
