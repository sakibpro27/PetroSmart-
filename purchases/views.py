"""Supplier and fuel purchase screens. Rules live in purchases.services."""

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.crud import TenantFormViewMixin
from sales.services import viewable_outlets
from tenants.permissions import BusinessMemberRequiredMixin, DealerRequiredMixin

from . import services
from .forms import AllocationFormSet, PurchaseFilterForm, PurchaseForm, SupplierForm
from .models import Supplier

# --- Suppliers (Dealer only) --------------------------------------------------


class SupplierListView(DealerRequiredMixin, ListView):
    template_name = "purchases/supplier_list.html"
    context_object_name = "suppliers"

    def get_queryset(self):
        return Supplier.objects.for_business(self.request.business).order_by("-is_active", "name")


class SupplierCreateView(TenantFormViewMixin, CreateView):
    model = Supplier
    form_class = SupplierForm
    success_url = reverse_lazy("purchases:supplier_list")


class SupplierUpdateView(TenantFormViewMixin, UpdateView):
    model = Supplier
    form_class = SupplierForm
    success_url = reverse_lazy("purchases:supplier_list")


# --- Purchases ----------------------------------------------------------------


class PurchaseListView(BusinessMemberRequiredMixin, ListView):
    template_name = "purchases/purchase_list.html"
    context_object_name = "purchases"
    paginate_by = 50

    @cached_property
    def filter_form(self):
        return PurchaseFilterForm(self.request.GET or None, user=self.request.user,
                                  outlets=viewable_outlets(self.request.user))

    def get_queryset(self):
        purchases = services.purchases_for(self.request.user).select_related("outlet", "supplier", "product")
        form = self.filter_form
        if form.is_bound and form.is_valid():
            data = form.cleaned_data
            if data["date_from"]:
                purchases = purchases.filter(delivery_date__gte=data["date_from"])
            if data["date_to"]:
                purchases = purchases.filter(delivery_date__lte=data["date_to"])
            for name in ("outlet", "product", "supplier"):
                if data[name]:
                    purchases = purchases.filter(**{name: data[name]})
        return purchases.annotate(received=Sum("receipts__litres")).order_by("-delivery_date", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for purchase in context["purchases"]:
            purchase.difference = (purchase.received or Decimal("0")) - purchase.invoiced_litres
        rows = self.object_list
        totals = rows.aggregate(invoiced=Sum("invoiced_litres"), amount=Sum("invoice_amount"))
        totals["received"] = sum((p.received or Decimal("0")) for p in rows)
        totals["difference"] = totals["received"] - (totals["invoiced"] or Decimal("0"))
        context.update(filter_form=self.filter_form, totals=totals, query=self.request.GET.urlencode())
        return context


class PurchaseFormView(BusinessMemberRequiredMixin, View):
    template_name = "purchases/purchase_form.html"

    @cached_property
    def purchase(self):
        if "pk" not in self.kwargs:
            return None
        return get_object_or_404(services.purchases_for(self.request.user), pk=self.kwargs["pk"])

    def _forms(self, data=None):
        user = self.request.user
        initial = None
        if self.purchase is not None and data is None:
            initial = [{"tank": r.tank, "litres": r.litres} for r in self.purchase.receipts.select_related("tank")]
        return (
            PurchaseForm(data, instance=self.purchase, user=user, prefix="purchase"),
            AllocationFormSet(data, initial=initial, prefix="tanks", form_kwargs={"user": user}),
        )

    def _render(self, form, formset):
        return render(self.request, self.template_name, {"form": form, "formset": formset, "purchase": self.purchase})

    def get(self, request, *args, **kwargs):
        if self.purchase is not None and services.is_locked(self.purchase):
            messages.info(request, "This delivery is locked because that day's tank stock is already submitted.")
            return redirect(self.purchase)
        return self._render(*self._forms())

    def post(self, request, *args, **kwargs):
        form, formset = self._forms(request.POST)
        if not (form.is_valid() and formset.is_valid()):
            return self._render(form, formset)
        allocations = [(f.cleaned_data["tank"], f.cleaned_data["litres"]) for f in formset.forms
                       if f.cleaned_data.get("tank")]
        try:
            purchase = services.save_purchase(form, allocations, user=request.user, request=request)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self._render(form, formset)
        messages.success(request, f"{purchase} saved. The received litres are now in tank stock.")
        return redirect(purchase)


class PurchaseDetailView(BusinessMemberRequiredMixin, DetailView):
    template_name = "purchases/purchase_detail.html"
    context_object_name = "purchase"

    def get_queryset(self):
        return services.purchases_for(self.request.user).select_related("outlet", "supplier", "product", "entered_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        purchase = self.object
        received = services.received_litres(purchase)
        context.update(
            received=received,
            difference=received - purchase.invoiced_litres,
            comparison=services.stock_comparison(purchase),
            locked=services.is_locked(purchase),
            can_change=self.request.user.accessible_outlets().filter(pk=purchase.outlet_id).exists(),
        )
        return context


class PurchaseDeleteView(BusinessMemberRequiredMixin, View):
    def post(self, request, pk):
        purchase = get_object_or_404(services.purchases_for(request.user), pk=pk)
        try:
            services.delete_purchase(purchase, user=request.user, request=request)
        except ValidationError as error:
            for message in error.messages:
                messages.error(request, message)
            return redirect(purchase)
        messages.success(request, "Fuel purchase deleted. The deletion is recorded in the audit log.")
        return redirect(reverse("purchases:purchase_list"))
