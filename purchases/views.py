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
from station.models import FuelProduct

from .forms import AllocationFormSet, ProductLineFormSet, PurchaseFilterForm, PurchaseForm, SupplierForm
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
        purchases = (services.purchases_for(self.request.user).select_related("outlet", "supplier")
                     .prefetch_related("lines__product", "receipts"))
        form = self.filter_form
        if form.is_bound and form.is_valid():
            data = form.cleaned_data
            if data["date_from"]:
                purchases = purchases.filter(delivery_date__gte=data["date_from"])
            if data["date_to"]:
                purchases = purchases.filter(delivery_date__lte=data["date_to"])
            for name in ("outlet", "supplier"):
                if data[name]:
                    purchases = purchases.filter(**{name: data[name]})
            if data["product"]:
                purchases = purchases.filter(lines__product=data["product"]).distinct()
        return purchases.order_by("-delivery_date", "-pk")

    @staticmethod
    def _figures(purchase):
        invoiced = sum((line.invoiced_litres for line in purchase.lines.all()), Decimal("0"))
        received = sum((receipt.litres for receipt in purchase.receipts.all()), Decimal("0"))
        return invoiced, received

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for purchase in context["purchases"]:
            purchase.invoiced, purchase.received = self._figures(purchase)
            purchase.difference = purchase.received - purchase.invoiced
        totals = {"invoiced": Decimal("0"), "received": Decimal("0"), "amount": Decimal("0")}
        for purchase in self.object_list:
            invoiced, received = self._figures(purchase)
            totals["invoiced"] += invoiced
            totals["received"] += received
            totals["amount"] += purchase.invoice_amount
        totals["difference"] = totals["received"] - totals["invoiced"]
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
        tanks_initial = lines_initial = None
        if data is None:
            if self.purchase is not None:
                tanks_initial = [{"tank": r.tank, "litres": r.litres} for r in self.purchase.receipts.select_related("tank")]
                lines_initial = [{"product": l.product, "invoiced_litres": l.invoiced_litres, "purchase_rate": l.purchase_rate}
                                 for l in self.purchase.lines.select_related("product")]
            else:
                # New invoice: one row each for MS and HSD, ready to fill (leave a row empty if not delivered).
                lines_initial = [{"product": p} for p in
                                 FuelProduct.objects.for_business(user.business).filter(is_active=True)
                                 .order_by("-category", "code")]  # MS (petrol) first, then HSD
        return (
            PurchaseForm(data, instance=self.purchase, user=user, prefix="purchase"),
            ProductLineFormSet(data, initial=lines_initial, prefix="lines", form_kwargs={"user": user}),
            AllocationFormSet(data, initial=tanks_initial, prefix="tanks", form_kwargs={"user": user}),
        )

    def _render(self, form, lines, formset):
        return render(self.request, self.template_name,
                      {"form": form, "lines": lines, "formset": formset, "purchase": self.purchase})

    def get(self, request, *args, **kwargs):
        if self.purchase is not None and services.is_locked(self.purchase):
            messages.info(request, "This delivery is locked because that day's tank stock is already saved.")
            return redirect(self.purchase)
        return self._render(*self._forms())

    def post(self, request, *args, **kwargs):
        form, lines, formset = self._forms(request.POST)
        if not (form.is_valid() and lines.is_valid() and formset.is_valid()):
            return self._render(form, lines, formset)
        products = [(f.cleaned_data["product"], f.cleaned_data["invoiced_litres"], f.cleaned_data["purchase_rate"])
                    for f in lines.forms if f.cleaned_data.get("product")]
        allocations = [(f.cleaned_data["tank"], f.cleaned_data["litres"]) for f in formset.forms
                       if f.cleaned_data.get("tank")]
        try:
            purchase = services.save_purchase(form, products, allocations, user=request.user, request=request)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self._render(form, lines, formset)
        messages.success(request, f"{purchase} saved. The received litres are now in tank stock.")
        return redirect(purchase)


class PurchaseDetailView(BusinessMemberRequiredMixin, DetailView):
    template_name = "purchases/purchase_detail.html"
    context_object_name = "purchase"

    def get_queryset(self):
        return services.purchases_for(self.request.user).select_related("outlet", "supplier", "entered_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        purchase = self.object
        received = services.received_litres(purchase)
        invoiced = purchase.total_invoiced_litres
        context.update(
            invoiced=invoiced,
            received=received,
            difference=received - invoiced,
            products=services.product_comparison(purchase),
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
