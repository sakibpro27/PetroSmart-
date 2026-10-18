"""Collections, customer credit, expenses and the operational summary."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from core.crud import TenantFormViewMixin
from sales.forms import ReviewNoteForm
from sales.services import viewable_outlets
from tenants.permissions import BusinessMemberRequiredMixin, DealerRequiredMixin

from . import services
from .forms import (
    CollectionLineFormSet, CollectionNotesForm, CreditAdjustmentForm, CreditCustomerForm, CreditSaleFormSet,
    CustomerPaymentForm, ExpenseCategoryForm, ExpenseForm, NewCollectionForm, PaymentMethodForm, PeriodFilterForm,
)
from .models import CreditCustomer, CustomerPayment, ExpenseCategory, PaymentMethod


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


# --- Shift collections ----------------------------------------------------------------


class CollectionMixin(BusinessMemberRequiredMixin):
    @cached_property
    def collection(self):
        return get_object_or_404(services.collections_for(self.request.user).select_related("outlet", "shift"),
                                 pk=self.kwargs["pk"])


class CollectionListView(BusinessMemberRequiredMixin, ListView):
    template_name = "finance/collection_list.html"
    context_object_name = "collections"
    paginate_by = 25

    def get_queryset(self):
        return services.collections_for(self.request.user).select_related("outlet", "shift").order_by(
            "-business_date", "-shift__sort_order", "outlet__code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for collection in context["collections"]:
            collection.figures = services.collection_figures(collection)
        return context


class CollectionCreateView(BusinessMemberRequiredMixin, FormView):
    template_name = "crud/form.html"
    form_class = NewCollectionForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="Record shift collections", page_subtitle="Cash, UPI, card and credit for one shift.",
                       cancel_url=reverse("finance:collection_list"))
        return context

    def form_valid(self, form):
        try:
            collection = services.create_collection(user=self.request.user, shift=form.cleaned_data["shift"],
                                                    business_date=form.cleaned_data["business_date"], request=self.request)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        return redirect("finance:collection_edit", pk=collection.pk)


class CollectionEditView(CollectionMixin, View):
    template_name = "finance/collection_edit.html"

    def _forms(self, data=None):
        c = self.collection
        return (
            CollectionLineFormSet(data, queryset=c.lines.select_related("method"), prefix="methods"),
            CreditSaleFormSet(data, queryset=c.credit_sales.select_related("customer"), prefix="credit",
                              form_kwargs={"business": c.business}),
            CollectionNotesForm(data, instance=c, prefix="collection"),
        )

    def _render(self, lines, credit, notes):
        return render(self.request, self.template_name, {
            "collection": self.collection, "lines": lines, "credit": credit, "notes_form": notes,
            "figures": services.collection_figures(self.collection),
        })

    def get(self, request, *args, **kwargs):
        if not services.can_edit_collection(self.collection, request.user):
            return redirect(self.collection)
        return self._render(*self._forms())

    def post(self, request, *args, **kwargs):
        if not services.can_edit_collection(self.collection, request.user):
            messages.error(request, "These collections are verified and locked.")
            return redirect(self.collection)
        forms = self._forms(request.POST)
        if not all(form.is_valid() for form in forms):
            messages.error(request, "Some amounts need attention. Nothing was saved.")
            return self._render(*forms)
        try:
            services.save_collection(self.collection, *forms, user=request.user, request=request)
        except ValidationError as error:
            _errors_to_messages(request, error)
            return redirect("finance:collection_edit", pk=self.collection.pk)
        for customer in services.customers_over_limit(self.collection):
            messages.warning(request, f"{customer.name} is now over their credit limit of ₹{customer.credit_limit}.")
        messages.success(request, "Collections saved.")
        return redirect(self.collection)


class CollectionDetailView(CollectionMixin, TemplateView):
    template_name = "finance/collection_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        c, user = self.collection, self.request.user
        context.update(
            collection=c, figures=services.collection_figures(c),
            lines=c.lines.select_related("method"), credit_sales=c.credit_sales.select_related("customer"),
            can_edit=services.can_edit_collection(c, user),
            can_verify=user.is_dealer and c.status == c.Status.OPEN,
            can_reopen=user.is_dealer and c.status == c.Status.VERIFIED,
            note_form=ReviewNoteForm(),
        )
        return context


class CollectionVerifyView(DealerRequiredMixin, CollectionMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            services.verify_collection(self.collection, user=request.user, request=request)
            messages.success(request, "Collections verified and locked.")
        except ValidationError as error:
            _errors_to_messages(request, error)
        return redirect(self.collection)


class CollectionReopenView(DealerRequiredMixin, CollectionMixin, View):
    def post(self, request, *args, **kwargs):
        form = ReviewNoteForm(request.POST)
        try:
            services.reopen_collection(self.collection, user=request.user,
                                       note=form.cleaned_data["note"] if form.is_valid() else "", request=request)
            messages.success(request, "Collections reopened for changes.")
        except ValidationError as error:
            _errors_to_messages(request, error)
        return redirect(self.collection)


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
        services.delete_payment(payment, user=request.user, request=request)
        messages.success(request, "Payment deleted. The deletion is recorded in the audit log.")
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
        return expenses.select_related("outlet", "category", "method", "entered_by")

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
        services.delete_expense(expense, user=request.user, request=request)
        messages.success(request, "Expense deleted. The deletion is recorded in the audit log.")
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
