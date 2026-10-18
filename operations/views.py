"""Shop inventory, employees and attendance, reminders and the audit log screen."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from audit.models import AuditLog
from core.crud import TenantFormViewMixin
from sales.forms import ReviewNoteForm
from sales.services import viewable_outlets
from tenants.permissions import BusinessMemberRequiredMixin, DealerRequiredMixin

from . import services
from .forms import (
    AttendanceFormSet, AttendancePickForm, AuditFilterForm, EmployeeForm, MovementForm, ReminderForm, ShopItemForm,
)
from .models import Attendance, Employee, Reminder, ShopItem, StockMovement

# --- Shop inventory ------------------------------------------------------------------


class InventoryView(BusinessMemberRequiredMixin, TemplateView):
    template_name = "operations/inventory.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        outlets = list(viewable_outlets(user).filter(is_active=True))
        today = timezone.localdate()
        context.update(
            rows=services.stock_table(user, outlets),
            movements=StockMovement.objects.for_business(user.business).filter(outlet__in=outlets)
            .select_related("item", "outlet", "entered_by")[:25],
            month_sales=services.shop_sales(user, outlets, today.replace(day=1), today),
        )
        return context


class ItemListView(DealerRequiredMixin, ListView):
    template_name = "operations/item_list.html"
    context_object_name = "items"

    def get_queryset(self):
        return ShopItem.objects.for_business(self.request.business).order_by("-is_active", "name")


class ItemCreateView(TenantFormViewMixin, CreateView):
    model, form_class = ShopItem, ShopItemForm
    success_url = reverse_lazy("operations:item_list")
    page_title = "Add shop item"


class ItemUpdateView(TenantFormViewMixin, UpdateView):
    model, form_class = ShopItem, ShopItemForm
    success_url = reverse_lazy("operations:item_list")
    page_title = "Edit shop item"


class MovementCreateView(BusinessMemberRequiredMixin, FormView):
    template_name = "crud/form.html"
    form_class = MovementForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="Record shop stock movement",
                       page_subtitle="Opening stock, purchase, sale or adjustment of lubricants and shop items.",
                       cancel_url=reverse("operations:inventory"))
        return context

    def form_valid(self, form):
        try:
            services.record_movement(form, user=self.request.user, request=self.request)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, "Stock movement recorded.")
        return redirect("operations:inventory")


# --- Employees and attendance ------------------------------------------------------------


class EmployeeListView(BusinessMemberRequiredMixin, ListView):
    template_name = "operations/employee_list.html"
    context_object_name = "employees"

    def get_queryset(self):
        return (Employee.objects.for_business(self.request.business)
                .filter(outlet__in=viewable_outlets(self.request.user)).select_related("outlet")
                .order_by("-is_active", "outlet__code", "name"))


class EmployeeCreateView(TenantFormViewMixin, CreateView):
    model, form_class = Employee, EmployeeForm
    success_url = reverse_lazy("operations:employee_list")


class EmployeeUpdateView(TenantFormViewMixin, UpdateView):
    model, form_class = Employee, EmployeeForm
    success_url = reverse_lazy("operations:employee_list")


class AttendanceView(BusinessMemberRequiredMixin, View):
    """Pick a date and shift, then mark each of that outlet's employees."""

    template_name = "operations/attendance.html"

    def get(self, request):
        pick = AttendancePickForm(request.GET or None, user=request.user)
        context = {"pick": pick, "formset": None}
        if request.GET and pick.is_valid():
            shift, day = pick.cleaned_data["shift"], pick.cleaned_data["business_date"]
            existing = {a.employee_id: a for a in Attendance.objects.filter(shift=shift, work_date=day)}
            employees = list(Employee.objects.for_business(request.business).filter(outlet=shift.outlet, is_active=True))
            initial = [{"employee_id": e.pk,
                        "status": existing[e.pk].status if e.pk in existing else Attendance.Status.PRESENT,
                        "duty": existing[e.pk].duty if e.pk in existing else ""} for e in employees]
            formset = AttendanceFormSet(initial=initial, prefix="att")
            context.update(formset=formset, rows=list(zip(formset.forms, employees)),
                           shift=shift, day=day, already_recorded=bool(existing))
        return render(request, self.template_name, context)

    def post(self, request):
        pick = AttendancePickForm(request.POST, user=request.user)
        formset = AttendanceFormSet(request.POST, prefix="att")
        if not (pick.is_valid() and formset.is_valid()):
            messages.error(request, "Please check the attendance entries.")
            return redirect("operations:attendance")
        shift, day = pick.cleaned_data["shift"], pick.cleaned_data["business_date"]
        employees = {e.pk: e for e in Employee.objects.for_business(request.business).filter(outlet=shift.outlet)}
        entries = []
        for form in formset:
            employee = employees.get(form.cleaned_data["employee_id"])
            if employee is None:  # not this outlet's employee (or another tenant's): refuse the whole save
                messages.error(request, "The attendance list did not match this outlet. Reload and try again.")
                return redirect("operations:attendance")
            entries.append((employee, form.cleaned_data["status"], form.cleaned_data["duty"]))
        try:
            services.save_attendance(user=request.user, shift=shift, work_date=day, entries=entries, request=request)
        except ValidationError as error:
            for message in error.messages:
                messages.error(request, message)
            return redirect("operations:attendance")
        messages.success(request, f"Attendance saved for {shift.outlet.code}, {day:%d %b %Y}, {shift.name} shift.")
        return redirect(f"{reverse('operations:attendance')}?business_date={day:%Y-%m-%d}&shift={shift.pk}")


# --- Reminders -------------------------------------------------------------------------


class ReminderListView(BusinessMemberRequiredMixin, TemplateView):
    template_name = "operations/reminder_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reminders = services.reminders_for(self.request.user).select_related("outlet", "completed_by")
        today = timezone.localdate()
        open_reminders = list(reminders.filter(completed_on__isnull=True).order_by("due_date"))
        for reminder in open_reminders:
            reminder.days_left = (reminder.due_date - today).days
            reminder.days_overdue = -reminder.days_left
        context.update(open_reminders=open_reminders,
                       done=reminders.filter(completed_on__isnull=False).order_by("-completed_on")[:20],
                       due_soon_days=services.DUE_SOON_DAYS)
        return context


class ReminderCreateView(TenantFormViewMixin, CreateView):
    model, form_class = Reminder, ReminderForm
    success_url = reverse_lazy("operations:reminder_list")


class ReminderUpdateView(TenantFormViewMixin, UpdateView):
    model, form_class = Reminder, ReminderForm
    success_url = reverse_lazy("operations:reminder_list")


class ReminderCompleteView(DealerRequiredMixin, View):
    def post(self, request, pk):
        reminder = get_object_or_404(Reminder.objects.for_business(request.business), pk=pk)
        form = ReviewNoteForm(request.POST)
        try:
            following = services.complete_reminder(reminder, user=request.user,
                                                   note=form.cleaned_data["note"] if form.is_valid() else "", request=request)
            messages.success(request, f"Marked done.{f' Next due on {following.due_date:%d %b %Y}.' if following else ''}")
        except ValidationError as error:
            for message in error.messages:
                messages.error(request, message)
        return redirect("operations:reminder_list")


# --- Audit log ---------------------------------------------------------------------------


class AuditLogView(DealerRequiredMixin, ListView):
    template_name = "operations/audit_log.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_queryset(self):
        self.filter_form = AuditFilterForm(self.request.GET or None, business=self.request.business)
        entries = AuditLog.objects.filter(business=self.request.business).select_related("user")
        if self.filter_form.is_bound and self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if data["date_from"]:
                entries = entries.filter(created_at__date__gte=data["date_from"])
            if data["date_to"]:
                entries = entries.filter(created_at__date__lte=data["date_to"])
            if data["user"]:
                entries = entries.filter(user=data["user"])
            if data["action"]:
                entries = entries.filter(action=data["action"])
            if data["q"]:
                entries = entries.filter(description__icontains=data["q"])
        return entries

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.copy()
        query.pop("page", None)
        context.update(filter_form=self.filter_form, query=query.urlencode())
        return context
