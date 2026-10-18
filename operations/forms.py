from django import forms
from django.utils import timezone

from core.forms import AuditedModelForm, BootstrapFormMixin, TenantModelForm
from sales.forms import NewSheetForm
from stock.forms import DATE_INPUT, DECIMAL_INPUT
from tenants.models import Outlet

from .models import Attendance, Employee, Reminder, ShopItem, StockMovement


class ShopItemForm(TenantModelForm):
    class Meta:
        model = ShopItem
        fields = ["name", "sku", "category", "unit", "selling_price", "reorder_level", "is_active"]
        labels = {"selling_price": "Selling price (₹ per unit)", "is_active": "Item active"}


class MovementForm(AuditedModelForm):
    class Meta:
        model = StockMovement
        fields = ["item", "outlet", "moved_on", "kind", "quantity", "unit_price", "reference", "notes"]
        labels = {"moved_on": "Date", "unit_price": "Price per unit (₹)"}
        widgets = {"moved_on": DATE_INPUT}
        help_texts = {"quantity": "For a sale enter the number sold; it is subtracted automatically. "
                                  "For an adjustment use a negative number to reduce stock."}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.business = user.business
        self.fields["item"].queryset = ShopItem.objects.for_business(user.business).filter(is_active=True)
        self.fields["outlet"].queryset = user.accessible_outlets()
        self.fields["moved_on"].initial = timezone.localdate()
        self.fields["moved_on"].widget.attrs["max"] = timezone.localdate().isoformat()
        self.fields["quantity"].widget.attrs.update({"inputmode": "decimal", "step": "0.01"})
        self.fields["unit_price"].widget.attrs.update({**DECIMAL_INPUT})

    def clean(self):
        cleaned = super().clean()
        # Sales are typed as the number sold and stored as negative (stock goes down).
        if cleaned.get("kind") == StockMovement.Kind.SALE and cleaned.get("quantity"):
            cleaned["quantity"] = -abs(cleaned["quantity"])
        return cleaned


class EmployeeForm(TenantModelForm):
    class Meta:
        model = Employee
        fields = ["name", "outlet", "job_title", "phone", "joined_on", "notes", "is_active"]
        labels = {"is_active": "Currently employed"}
        widgets = {"joined_on": DATE_INPUT}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["outlet"].queryset = Outlet.objects.for_business(self.business)


class AttendancePickForm(NewSheetForm):
    """Choose date and outlet/shift, exactly like a Daily Sales sheet."""


class AttendanceRowForm(BootstrapFormMixin, forms.Form):
    employee_id = forms.IntegerField(widget=forms.HiddenInput)
    status = forms.ChoiceField(choices=Attendance.Status.choices)
    duty = forms.CharField(max_length=60, required=False)


AttendanceFormSet = forms.formset_factory(AttendanceRowForm, extra=0)


class ReminderForm(TenantModelForm):
    class Meta:
        model = Reminder
        fields = ["title", "category", "outlet", "due_date", "repeat_months", "notes"]
        labels = {"repeat_months": "Repeat every (months)"}
        widgets = {"due_date": DATE_INPUT, "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["outlet"].queryset = Outlet.objects.for_business(self.business)
        self.fields["outlet"].empty_label = "Whole business"


class AuditFilterForm(BootstrapFormMixin, forms.Form):
    date_from = forms.DateField(label="From", required=False, widget=DATE_INPUT)
    date_to = forms.DateField(label="To", required=False, widget=DATE_INPUT)
    user = forms.ModelChoiceField(queryset=None, required=False, empty_label="Anyone")
    action = forms.ChoiceField(required=False)
    q = forms.CharField(label="Contains", required=False, max_length=100)

    def __init__(self, *args, business, **kwargs):
        from audit.models import AuditLog

        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = business.users.order_by("username")
        self.fields["action"].choices = [("", "Any action"), *AuditLog.Action.choices]
