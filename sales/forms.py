from datetime import date
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.forms import BootstrapFormMixin
from station.models import Dispenser, FuelProduct, Shift

from .calculations import calculate_line
from .models import DENOMINATIONS, DailySalesSheet
from .reports import GROUPINGS
from .services import viewable_outlets

DECIMAL_INPUT = {"inputmode": "decimal", "step": "0.01", "min": "0", "autocomplete": "off"}
DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
TIME_INPUT = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")
ZERO = Decimal("0")


class ShiftChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, shift):
        return f"{shift.outlet.code} · {shift.name} ({shift.start_time:%H:%M}–{shift.end_time:%H:%M})"


class DispenserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, dispenser):
        return f"{dispenser.outlet.code} · {dispenser.code}"


class NewSheetForm(BootstrapFormMixin, forms.Form):
    """Date and outlet/shift picker, also used by attendance."""

    business_date = forms.DateField(label="Date", widget=DATE_INPUT)
    shift = ShiftChoiceField(queryset=Shift.objects.none(), label="Outlet and shift")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["business_date"].initial = timezone.localdate()
        self.fields["business_date"].widget.attrs["max"] = timezone.localdate().isoformat()
        self.fields["shift"].queryset = (
            Shift.objects.for_business(user.business)
            .filter(outlet__in=user.accessible_outlets(), is_active=True)
            .select_related("outlet").order_by("outlet__code", "sort_order")
        )


# --- Shift Card ------------------------------------------------------------------------


class CardHeaderForm(BootstrapFormMixin, forms.ModelForm):
    """The top of the Shift Card and its money fields. Date, shift and MPD/DU are fixed once saved."""

    business_date = forms.DateField(label="Date", widget=DATE_INPUT)
    shift = ShiftChoiceField(queryset=Shift.objects.none(), label="Shift")
    dispenser = DispenserChoiceField(queryset=Dispenser.objects.none(), label="MPD / DU")

    class Meta:
        model = DailySalesSheet
        fields = ["employee", "cashier_name", "helper_name", "tanker_card", "time_from", "time_to", "notes",
                  "general_credit", "general_credit_party", "bank_card", "company_card", "phone_wallet",
                  *[f"notes_{d}" for d in DENOMINATIONS], "coins"]
        labels = {"employee": "Employee name", "tanker_card": "Tanker card?", "time_from": "Time from",
                  "time_to": "Time to", "general_credit_party": "Gen. credit party"}
        widgets = {"time_from": TIME_INPUT, "time_to": TIME_INPUT}

    def __init__(self, *args, user, editing=False, **kwargs):
        from operations.models import Employee  # operations builds on sales

        super().__init__(*args, **kwargs)
        outlets = user.accessible_outlets()
        today = timezone.localdate()
        self.fields["business_date"].initial = today
        self.fields["business_date"].widget.attrs["max"] = today.isoformat()
        self.fields["shift"].queryset = (Shift.objects.for_business(user.business)
                                         .filter(outlet__in=outlets, is_active=True)
                                         .select_related("outlet").order_by("outlet__code", "sort_order"))
        self.fields["dispenser"].queryset = (Dispenser.objects.for_business(user.business)
                                             .filter(outlet__in=outlets, is_active=True)
                                             .select_related("outlet").order_by("outlet__code", "code"))
        self.fields["employee"].queryset = (Employee.objects.for_business(user.business)
                                            .filter(outlet__in=outlets, is_active=True).select_related("outlet"))
        self.fields["employee"].required = True
        for name in ("general_credit", "bank_card", "company_card", "phone_wallet", "coins"):
            self.fields[name].widget.attrs.update({**DECIMAL_INPUT, "data-money": name})
        for d in DENOMINATIONS:
            field = self.fields[f"notes_{d}"]
            field.label = f"{d} ×"
            field.widget.attrs.update({"inputmode": "numeric", "min": "0", "data-note": str(d)})
        if editing:
            for name in ("business_date", "shift", "dispenser"):
                self.fields[name].disabled = True
                self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        shift, dispenser, employee = cleaned.get("shift"), cleaned.get("dispenser"), cleaned.get("employee")
        if shift and dispenser and shift.outlet_id != dispenser.outlet_id:
            self.add_error("shift", "This shift is at a different outlet from the MPD / DU.")
        if employee and dispenser and employee.outlet_id != dispenser.outlet_id:
            self.add_error("employee", "This employee works at a different outlet.")
        if cleaned.get("general_credit") and not cleaned.get("general_credit_party", "").strip():
            self.add_error("general_credit_party", "Write who the general credit was given to.")
        return cleaned


class NozzleRowForm(BootstrapFormMixin, forms.Form):
    """One nozzle row: the opening reading and rate are shown, never accepted from the browser."""

    nozzle_id = forms.IntegerField(widget=forms.HiddenInput)
    closing_reading = forms.DecimalField(max_digits=12, decimal_places=2, min_value=ZERO, label="Closing")
    testing_litres = forms.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, initial=ZERO,
                                        label="Testing")
    meter_reset = forms.BooleanField(required=False, label="Meter rolled over or replaced during this shift")
    reading_before_reset = forms.DecimalField(max_digits=12, decimal_places=2, min_value=ZERO, required=False,
                                              label="Last reading before reset (L)")
    reading_after_reset = forms.DecimalField(max_digits=12, decimal_places=2, min_value=ZERO, required=False,
                                             label="First reading after reset (L)")
    notes = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, row=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.row = row or {}
        for name in ("closing_reading", "testing_litres", "reading_before_reset", "reading_after_reset"):
            self.fields[name].widget.attrs.update(DECIMAL_INPUT)
        self.fields["closing_reading"].widget.attrs["data-role"] = "closing"
        self.fields["testing_litres"].widget.attrs["data-role"] = "testing"
        self.fields["meter_reset"].widget.attrs["data-role"] = "reset"
        self.fields["reading_before_reset"].widget.attrs["data-role"] = "before"
        self.fields["reading_after_reset"].widget.attrs["data-role"] = "after"
        self.fields["notes"].widget.attrs["placeholder"] = "Notes (required for a meter reset)"

    def clean(self):
        cleaned = super().clean()
        if self.errors or not self.row:
            return cleaned
        if cleaned.get("meter_reset") and not cleaned.get("notes", "").strip():
            self.add_error("notes", "Explain the meter rollover or replacement.")
        try:
            calculate_line(self.row["opening"], cleaned["closing_reading"], cleaned.get("testing_litres") or ZERO,
                           self.row["price"], meter_reset=cleaned.get("meter_reset"),
                           before_reset=cleaned.get("reading_before_reset"), after_reset=cleaned.get("reading_after_reset"))
        except ValidationError as error:
            for field, messages in error.message_dict.items():
                for message in messages:
                    self.add_error(field if field in self.fields else None, message)
        return cleaned


class BaseNozzleFormSet(forms.BaseFormSet):
    def __init__(self, *args, rows=(), **kwargs):
        self.rows = list(rows)
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["row"] = self.rows[index] if index is not None and index < len(self.rows) else None
        return kwargs


NozzleFormSet = forms.formset_factory(NozzleRowForm, formset=BaseNozzleFormSet, extra=0)


class _DetailRowForm(BootstrapFormMixin, forms.Form):
    """A detail row is skipped when left completely empty."""

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.empty_permitted = True
        self.use_required_attribute = False
        for field in self.fields.values():
            if isinstance(field, forms.DecimalField):
                field.widget.attrs.update({**DECIMAL_INPUT, "data-sum": "1"})


class CreditRowForm(_DetailRowForm):
    """
    One credit slip. Enter the amount or the litres; the other is worked out
    from the day's selling price. The slip number is given automatically when
    the card is saved and cannot be typed.
    """

    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    slip_no = forms.CharField(required=False, disabled=True, label="Slip no.")
    customer = forms.ModelChoiceField(queryset=None, required=False)
    product = forms.ModelChoiceField(queryset=None, required=False, label="Item")
    litres = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False,
                                label="Qty (L)")
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"), required=False)
    vehicle_number = forms.CharField(max_length=20, required=False, label="Vehicle")

    def __init__(self, *args, business, **kwargs):
        from finance.models import CreditCustomer

        super().__init__(*args, business=business, **kwargs)
        self.fields["customer"].queryset = CreditCustomer.objects.for_business(business).filter(is_active=True)
        self.fields["product"].queryset = FuelProduct.objects.for_business(business).filter(is_active=True)
        self.fields["slip_no"].widget.attrs.update({"placeholder": "Auto", "class": "form-control sc-slip",
                                                    "tabindex": "-1"})
        self.fields["litres"].widget.attrs.pop("data-sum", None)
        self.fields["litres"].widget.attrs["data-credit-litres"] = "1"
        self.fields["amount"].widget.attrs["data-credit-amount"] = "1"
        self.fields["product"].widget.attrs["data-credit-product"] = "1"

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(name) for name in ("customer", "product", "litres", "amount", "vehicle_number")):
            return {}  # cleared or never filled: no slip (an existing slip in this row is removed)
        if not cleaned.get("customer"):
            self.add_error("customer", "Choose the customer.")
        if not cleaned.get("product"):
            self.add_error("product", "Choose the item.")
        if not cleaned.get("amount") and not cleaned.get("litres"):
            self.add_error("amount", "Enter the amount or the litres.")
        return cleaned


class ReceiptRowForm(_DetailRowForm):
    customer = forms.ModelChoiceField(queryset=None)
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    reference = forms.CharField(max_length=100, required=False, label="Receipt no.")

    def __init__(self, *args, business, **kwargs):
        from finance.models import CreditCustomer

        super().__init__(*args, business=business, **kwargs)
        self.fields["customer"].queryset = CreditCustomer.objects.for_business(business).filter(is_active=True)


class LubeRowForm(_DetailRowForm):
    item = forms.ModelChoiceField(queryset=None)
    quantity = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), label="Qty")
    rate = forms.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, label="Rate (₹)")

    def __init__(self, *args, business, **kwargs):
        from operations.models import ShopItem

        super().__init__(*args, business=business, **kwargs)
        self.fields["item"].queryset = ShopItem.objects.for_business(business).filter(is_active=True)
        self.fields["quantity"].widget.attrs.pop("data-sum", None)
        self.fields["rate"].widget.attrs.pop("data-sum", None)
        self.fields["quantity"].widget.attrs["data-qty"] = "1"
        self.fields["rate"].widget.attrs["data-rate"] = "1"


class ExpenseRowForm(_DetailRowForm):
    category = forms.ModelChoiceField(queryset=None)
    description = forms.CharField(max_length=200)
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))

    def __init__(self, *args, business, **kwargs):
        from finance.models import ExpenseCategory

        super().__init__(*args, business=business, **kwargs)
        self.fields["category"].queryset = ExpenseCategory.objects.for_business(business).filter(is_active=True)


def detail_formset(form_class):
    return forms.formset_factory(form_class, extra=1, max_num=50, validate_max=True)


CreditFormSet = detail_formset(CreditRowForm)
ReceiptFormSet = detail_formset(ReceiptRowForm)
LubeFormSet = detail_formset(LubeRowForm)
ExpenseFormSet = detail_formset(ExpenseRowForm)


def filled_rows(formset, *names):
    """Values of the non-empty rows of a valid detail formset, as tuples in `names` order."""
    return [tuple(form.cleaned_data.get(name, "") for name in names) for form in formset.forms if form.cleaned_data]


# --- Other forms ---------------------------------------------------------------------


class ReviewNoteForm(BootstrapFormMixin, forms.Form):
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), max_length=1000)


class CorrectionRequestForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), max_length=1000,
        help_text="Explain why the saved figures are wrong. This is kept in the card's history.",
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
                continue
            if tuple(values) != (line.closing_reading, line.testing_litres, line.price_per_litre):
                self.changes.append((line, *values))
        if not self.errors and not self.changes:
            raise forms.ValidationError("Change at least one value, or cancel.")
        return cleaned


class SummaryFilterForm(BootstrapFormMixin, forms.Form):
    group_by = forms.ChoiceField(choices=[(key, label) for key, (label, _) in GROUPINGS.items()], initial="day", label="Group by")
    date_from = forms.DateField(label="From", widget=DATE_INPUT)
    date_to = forms.DateField(label="To", widget=DATE_INPUT)
    outlet = forms.ModelChoiceField(queryset=None, required=False, empty_label="All outlets")
    product = forms.ModelChoiceField(queryset=None, required=False, empty_label="All products")

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
