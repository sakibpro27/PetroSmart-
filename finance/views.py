"""Customer credit, expenses, payment settings and the operational summary."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from core.crud import TenantFormViewMixin
from sales.services import viewable_outlets
from tenants.permissions import BusinessMemberRequiredMixin, DealerRequiredMixin

from . import services
from .forms import (
    BillCancelForm, BillFilterForm, BillForm, CreditAdjustmentForm, CreditCustomerForm, CustomerPaymentForm, ExpenseCategoryForm, ExpenseForm, PaymentMethodForm,
    PeriodFilterForm,
)
from .models import CreditCustomer, CustomerPayment, ExpenseCategory, PaymentMethod
from .words import rupees_in_words


def _errors_to_messages(request, error):
    for message in error.messages:
        messages.error(request, message)


# --- Dealer settings: payment methods and expense categories ----------------------------


class FinanceSettingsView(DealerRequiredMixin, TemplateView):
    template_name = "finance/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["methods"] = PaymentMethod.objects.for_business(self.request.business)
        context["categories"] = ExpenseCategory.objects.for_business(self.request.business)
        return context


class SettingsFormMixin(TenantFormViewMixin):
    success_url = reverse_lazy("finance:settings")


class MethodCreateView(SettingsFormMixin, CreateView):
    model, form_class = PaymentMethod, PaymentMethodForm


class MethodUpdateView(SettingsFormMixin, UpdateView):
    model, form_class = PaymentMethod, PaymentMethodForm


class CategoryCreateView(SettingsFormMixin, CreateView):
    model, form_class = ExpenseCategory, ExpenseCategoryForm


class CategoryUpdateView(SettingsFormMixin, UpdateView):
    model, form_class = ExpenseCategory, ExpenseCategoryForm


# --- Credit customers ---------------------------------------------------------------------


class CustomerListView(BusinessMemberRequiredMixin, ListView):
    template_name = "finance/customer_list.html"
    context_object_name = "customers"

    def get_queryset(self):
        return CreditCustomer.objects.for_business(self.request.business).order_by("-is_active", "name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        total = 0
        for customer in context["customers"]:
            customer.current_balance = customer.balance()
            customer.over_limit = customer.credit_limit is not None and customer.current_balance > customer.credit_limit
            total += customer.current_balance
        context["outstanding_total"] = total
        return context


class CustomerCreateView(TenantFormViewMixin, CreateView):
    model, form_class = CreditCustomer, CreditCustomerForm
    success_url = reverse_lazy("finance:customer_list")


class CustomerUpdateView(TenantFormViewMixin, UpdateView):
    model, form_class = CreditCustomer, CreditCustomerForm

    def get_success_url(self):
        return self.object.get_absolute_url()


class CustomerLedgerView(BusinessMemberRequiredMixin, TemplateView):
    template_name = "finance/customer_ledger.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = get_object_or_404(CreditCustomer.objects.for_business(self.request.business), pk=self.kwargs["pk"])
        rows = services.ledger(customer)
        balance = rows[-1]["balance"] if rows else 0
        context.update(customer=customer, rows=rows, balance=balance,
                       over_limit=customer.credit_limit is not None and balance > customer.credit_limit,
                       adjustment_form=CreditAdjustmentForm() if self.request.user.is_dealer else None)
        return context


class PaymentCreateView(BusinessMemberRequiredMixin, FormView):
    template_name = "crud/form.html"
    form_class = CustomerPaymentForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_initial(self):
        return {"customer": self.request.GET.get("customer")}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="Record payment from a credit customer",
                       page_subtitle="This reduces the customer's outstanding balance.",
                       cancel_url=reverse("finance:customer_list"))
        return context

    def form_valid(self, form):
        try:
            payment = services.record_payment(form, user=self.request.user, request=self.request)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, f"Payment of ₹{payment.amount} recorded for {payment.customer}.")
        return redirect(payment.customer)


class PaymentDeleteView(DealerRequiredMixin, View):
    def post(self, request, pk):
        payment = get_object_or_404(CustomerPayment.objects.for_business(request.business).select_related("customer"), pk=pk)
        customer = payment.customer
        try:
            services.delete_payment(payment, user=request.user, request=request)
            messages.success(request, "Payment deleted. The deletion is recorded in the audit log.")
        except ValidationError as error:
            _errors_to_messages(request, error)
        return redirect(customer)


class AdjustmentCreateView(DealerRequiredMixin, View):
    def post(self, request, pk):
        customer = get_object_or_404(CreditCustomer.objects.for_business(request.business), pk=pk)
        form = CreditAdjustmentForm(request.POST)
        if form.is_valid():
            services.record_adjustment(form, customer, user=request.user, request=request)
            messages.success(request, "Balance adjusted.")
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
        return redirect(customer)


# --- Expenses -----------------------------------------------------------------------------


class ExpenseListView(BusinessMemberRequiredMixin, ListView):
    template_name = "finance/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 50

    @cached_property
    def filter_form(self):
        return PeriodFilterForm(self.request.GET or None, outlets=viewable_outlets(self.request.user))

    def get_queryset(self):
        date_from, date_to, outlet = self.filter_form.period()
        expenses = services.expenses_for(self.request.user).filter(expense_date__range=(date_from, date_to))
        if outlet:
            expenses = expenses.filter(outlet=outlet)
        return expenses.select_related("outlet", "category", "method", "entered_by", "sheet")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = self.object_list
        context.update(
            filter_form=self.filter_form,
            by_category=rows.values("category__name").annotate(total=Sum("amount")).order_by("-total"),
            total=rows.aggregate(total=Sum("amount"))["total"],
        )
        return context


class ExpenseFormView(BusinessMemberRequiredMixin, FormView):
    template_name = "crud/form.html"
    form_class = ExpenseForm

    @cached_property
    def expense(self):
        if "pk" not in self.kwargs:
            return None
        return get_object_or_404(services.expenses_for(self.request.user), pk=self.kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = {**super().get_form_kwargs(), "user": self.request.user}
        if self.expense is not None:
            kwargs["instance"] = self.expense
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="Edit expense" if self.expense else "Record expense",
                       cancel_url=reverse("finance:expense_list"))
        return context

    def form_valid(self, form):
        try:
            services.save_expense(form, user=self.request.user, request=self.request)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, "Expense saved.")
        return redirect("finance:expense_list")


class ExpenseDeleteView(BusinessMemberRequiredMixin, View):
    def post(self, request, pk):
        expense = get_object_or_404(services.expenses_for(request.user), pk=pk)
        try:
            services.delete_expense(expense, user=request.user, request=request)
            messages.success(request, "Expense deleted. The deletion is recorded in the audit log.")
        except ValidationError as error:
            _errors_to_messages(request, error)
        return redirect("finance:expense_list")


# --- Operational summary --------------------------------------------------------------


class OperationalSummaryView(DealerRequiredMixin, TemplateView):
    template_name = "finance/summary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        outlets = viewable_outlets(self.request.user)
        form = PeriodFilterForm(self.request.GET or None, outlets=outlets)
        date_from, date_to, outlet = form.period()
        if outlet:
            outlets = outlets.filter(pk=outlet.pk)
        context.update(form=form, date_from=date_from, date_to=date_to,
                       summary=services.operational_summary(business=self.request.business, outlets=outlets,
                                                            date_from=date_from, date_to=date_to),
                       outstanding=services.outstanding_total(self.request.business))
        return context


# --- Credit bills -------------------------------------------------------------------------


class BillCreateView(BusinessMemberRequiredMixin, View):
    """
    Make a bill for one customer: choose the outlet and the date, check the
    slips that will go on it, then create it. The bill number is automatic.
    """

    template_name = "finance/bill_form.html"

    @cached_property
    def customer(self):
        return get_object_or_404(CreditCustomer.objects.for_business(self.request.business), pk=self.kwargs["pk"])

    def _render(self, form):
        preview = None
        if form.is_bound and form.is_valid():
            preview = services.bill_preview(self.customer, form.cleaned_data["outlet"], form.cleaned_data["bill_date"])
        return render(self.request, self.template_name, {"customer": self.customer, "form": form, "preview": preview})

    def get(self, request, *args, **kwargs):
        user = request.user
        data = request.GET if "bill_date" in request.GET else None
        form = BillForm(data, user=user)
        if data is None and user.accessible_outlets().count() == 1:
            # One outlet: show its slips straight away.
            form = BillForm({"outlet": user.accessible_outlets().get().pk,
                             "bill_date": timezone.localdate().isoformat()}, user=user)
        return self._render(form)

    def post(self, request, *args, **kwargs):
        form = BillForm(request.POST, user=request.user)
        if not form.is_valid():
            return self._render(form)
        try:
            bill = services.create_bill(self.customer, form.cleaned_data["outlet"], form.cleaned_data["bill_date"],
                                        user=request.user, request=request)
        except ValidationError as error:
            _errors_to_messages(request, error)
            return self._render(form)
        messages.success(request, f"Bill {bill.bill_no} created for ₹{bill.amount:,.2f}.")
        return redirect(bill)


class BillListView(BusinessMemberRequiredMixin, ListView):
    template_name = "finance/bill_list.html"
    context_object_name = "bills"
    paginate_by = 50

    @cached_property
    def filter_form(self):
        return BillFilterForm(self.request.GET or None, business=self.request.business,
                              outlets=viewable_outlets(self.request.user))

    def get_queryset(self):
        bills = services.bills_for(self.request.user).select_related("customer", "outlet")
        if self.filter_form.is_bound and self.filter_form.is_valid():
            for name in ("customer", "outlet"):
                if self.filter_form.cleaned_data[name]:
                    bills = bills.filter(**{name: self.filter_form.cleaned_data[name]})
        return bills.order_by("-bill_date", "-bill_no")

    def get_context_data(self, **kwargs):
        return super().get_context_data(filter_form=self.filter_form, query=self.request.GET.urlencode(), **kwargs)


class BillDetailView(BusinessMemberRequiredMixin, DetailView):
    """The printable bill, laid out like a dealer's credit invoice."""

    template_name = "finance/bill_detail.html"
    context_object_name = "bill"

    def get_queryset(self):
        return services.bills_for(self.request.user).select_related("outlet", "customer", "created_by", "cancelled_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bill = self.object
        context.update(
            slips=bill.sales.select_related("sheet", "product").order_by("sheet__business_date", "slip_no"),
            summary=services.bill_summary(bill),
            amount_words=rupees_in_words(bill.amount),
            terms=[line.strip() for line in bill.outlet.bill_terms.splitlines() if line.strip()],
            cancel_form=BillCancelForm() if self.request.user.is_dealer and not bill.is_cancelled else None,
            print_now=self.request.GET.get("print") == "1",
        )
        return context


class BillCancelView(DealerRequiredMixin, View):
    def post(self, request, pk):
        bill = get_object_or_404(services.bills_for(request.user), pk=pk)
        form = BillCancelForm(request.POST)
        try:
            if not form.is_valid():
                raise ValidationError("Give a reason for cancelling the bill.")
            services.cancel_bill(bill, form.cleaned_data["reason"], user=request.user, request=request)
        except ValidationError as error:
            _errors_to_messages(request, error)
            return redirect(bill)
        messages.success(request, f"Bill {bill.bill_no} cancelled. Its slips will go on the next bill.")
        return redirect(bill)
