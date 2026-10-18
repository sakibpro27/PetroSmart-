from datetime import date

from django import forms
from django.db.models import Q
from django.utils import timezone

from core.forms import AuditedModelForm, BootstrapFormMixin, TenantModelForm
from stock.forms import DATE_INPUT, DECIMAL_INPUT

from .models import CreditAdjustment, CreditCustomer, CustomerPayment, Expense, ExpenseCategory, PaymentMethod

# --- Dealer settings ------------------------------------------------------------


class PaymentMethodForm(TenantModelForm):
    class Meta:
        model = PaymentMethod
        fields = ["name", "kind", "sort_order", "is_active"]
        labels = {"sort_order": "Display order", "is_active": "Method active"}


class ExpenseCategoryForm(TenantModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name", "is_active"]
        labels = {"is_active": "Category active"}


class CreditCustomerForm(TenantModelForm):
    class Meta:
        model = CreditCustomer
        fields = ["name", "phone", "vehicles", "address", "credit_limit", "opening_balance", "opening_balance_date", "is_active"]
        labels = {"credit_limit": "Credit limit (₹)", "opening_balance": "Opening balance owed (₹)", "is_active": "Customer active"}
        widgets = {"address": forms.Textarea(attrs={"rows": 2}), "opening_balance_date": DATE_INPUT}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["opening_balance_date"].initial = timezone.localdate()
        if self.instance.pk:
            # The opening balance is the start of the ledger; later changes go through adjustments.
            for name in ("opening_balance", "opening_balance_date"):
                self.fields[name].disabled = True
                self.fields[name].help_text = "Fixed once the customer is created. Use an adjustment to change the balance."


# --- Credit payments and adjustments ---------------------------------------------------


class CustomerPaymentForm(AuditedModelForm):
    class Meta:
        model = CustomerPayment
        fields = ["customer", "outlet", "received_on", "amount", "method", "reference", "notes"]
        labels = {"amount": "Amount received (₹)", "method": "Received by"}
        widgets = {"received_on": DATE_INPUT}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.business = user.business
        self.fields["customer"].queryset = CreditCustomer.objects.for_business(user.business).filter(is_active=True)
        self.fields["outlet"].queryset = user.accessible_outlets()
        self.fields["method"].queryset = PaymentMethod.objects.for_business(user.business).filter(is_active=True)
        self.fields["received_on"].initial = timezone.localdate()
        self.fields["received_on"].widget.attrs["max"] = timezone.localdate().isoformat()
        self.fields["amount"].widget.attrs.update({**DECIMAL_INPUT, "min": "0.01"})


class CreditAdjustmentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CreditAdjustment
        fields = ["adjusted_on", "amount", "reason"]
        labels = {"amount": "Adjustment (₹)"}
        widgets = {"adjusted_on": DATE_INPUT}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["adjusted_on"].initial = timezone.localdate()
        self.fields["amount"].widget.attrs.update({"inputmode": "decimal", "step": "0.01"})


# --- Expenses -----------------------------------------------------------------------------


class ExpenseForm(AuditedModelForm):
    class Meta:
        model = Expense
        fields = ["outlet", "expense_date", "category", "description", "amount", "method", "paid_to", "reference", "notes"]
        labels = {"amount": "Amount (₹)", "expense_date": "Date"}
        widgets = {"expense_date": DATE_INPUT}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.business = user.business
        self.fields["outlet"].queryset = user.accessible_outlets()
        current = Q(pk=self.instance.category_id) if self.instance.category_id else Q(pk__in=[])
        self.fields["category"].queryset = ExpenseCategory.objects.for_business(user.business).filter(Q(is_active=True) | current)
        current = Q(pk=self.instance.method_id) if self.instance.method_id else Q(pk__in=[])
        self.fields["method"].queryset = PaymentMethod.objects.for_business(user.business).filter(Q(is_active=True) | current)
        self.fields["expense_date"].initial = timezone.localdate()
        self.fields["expense_date"].widget.attrs["max"] = timezone.localdate().isoformat()
        self.fields["amount"].widget.attrs.update({**DECIMAL_INPUT, "min": "0.01"})


class PeriodFilterForm(BootstrapFormMixin, forms.Form):
    date_from = forms.DateField(label="From", widget=DATE_INPUT)
    date_to = forms.DateField(label="To", widget=DATE_INPUT)
    outlet = forms.ModelChoiceField(queryset=None, required=False, empty_label="All outlets")

    def __init__(self, *args, outlets, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["date_from"].initial = date(today.year, today.month, 1)
        self.fields["date_to"].initial = today
        self.fields["outlet"].queryset = outlets

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("date_from") and cleaned.get("date_to") and cleaned["date_from"] > cleaned["date_to"]:
            self.add_error("date_to", "The end date must be on or after the start date.")
        return cleaned

    def period(self):
        """(date_from, date_to, outlet) from valid input, or the defaults."""
        if self.is_bound and self.is_valid():
            return self.cleaned_data["date_from"], self.cleaned_data["date_to"], self.cleaned_data["outlet"]
        return self.fields["date_from"].initial, self.fields["date_to"].initial, None
