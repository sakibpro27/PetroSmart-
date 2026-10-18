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
from station.models import FuelProduct, Tank

from .forms import PurchaseFilterForm, PurchaseForm, PurchaseLineFormSet, SupplierForm
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
    """The purchase invoice: header, one row per item and tank, totals and remark."""

    template_name = "purchases/purchase_form.html"

    @cached_property
    def purchase(self):
        if "pk" not in self.kwargs:
            return None
        return get_object_or_404(services.purchases_for(self.request.user), pk=self.kwargs["pk"])

    def _initial_lines(self):
        user = self.request.user
        if self.purchase is not None:
            return [{"product": l.product, "tank": l.tank, "quantity_kl": l.quantity_kl, "rate_per_kl": l.rate_per_kl,
                     "delivery_charges": l.delivery_charges, "vat": l.vat, "cess": l.cess, "tcs": l.tcs,
                     "received_litres": l.received_litres}
                    for l in self.purchase.lines.select_related("product", "tank")]
        # New invoice: one row per product, with the tank filled in when the outlet has only one for it.
        outlets = user.accessible_outlets()
        tanks = Tank.objects.for_business(user.business).filter(outlet__in=outlets, is_active=True)
        rows = []
        for product in (FuelProduct.objects.for_business(user.business).filter(is_active=True)
                        .order_by("-category", "code")):  # MS (petrol) first, then HSD
            product_tanks = [t for t in tanks if t.product_id == product.pk]
            rows.append({"product": product, "tank": product_tanks[0] if len(product_tanks) == 1 else None})
        return rows

    def _forms(self, data=None):
        user = self.request.user
        return (
            PurchaseForm(data, instance=self.purchase, user=user, prefix="purchase"),
            PurchaseLineFormSet(data, initial=None if data else self._initial_lines(), prefix="lines",
                                form_kwargs={"user": user}),
        )

    def _render(self, form, lines):
        tanks = {str(t.pk): {"outlet": str(t.outlet_id), "product": str(t.product_id)}
                 for t in lines.empty_form.fields["tank"].queryset}
        return render(self.request, self.template_name,
                      {"form": form, "lines": lines, "purchase": self.purchase, "tank_map": tanks})

    def get(self, request, *args, **kwargs):
        if self.purchase is not None and services.is_locked(self.purchase):
            messages.info(request, "This delivery is locked because that day's tank stock is already saved.")
            return redirect(self.purchase)
        return self._render(*self._forms())

    def post(self, request, *args, **kwargs):
        form, lines = self._forms(request.POST)
        if not (form.is_valid() and lines.is_valid()):
            return self._render(form, lines)
        values = [v for v in (f.line_values() for f in lines.forms) if v]
        try:
            purchase = services.save_purchase(form, values, user=request.user, request=request)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self._render(form, lines)
        messages.success(request, f"{purchase} saved: {purchase.invoice_amount:,.2f}. "
                                  "The received litres are now in tank stock.")
        return redirect(purchase)


class PurchaseDetailView(BusinessMemberRequiredMixin, DetailView):
    template_name = "purchases/purchase_detail.html"
    context_object_name = "purchase"

    def get_queryset(self):
        return services.purchases_for(self.request.user).select_related("outlet", "supplier", "entered_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        purchase = self.object
        lines = list(purchase.lines.select_related("product", "tank"))
        invoiced = sum((line.invoiced_litres for line in lines), Decimal("0"))
        received = sum((line.received for line in lines), Decimal("0"))
        context.update(
            lines=lines,
            invoiced=invoiced,
            received=received,
            difference=received - invoiced,
            totals={name: sum((getattr(line, name) for line in lines), Decimal("0"))
                    for name in ("base_amount", "delivery_charges", "vat", "cess", "tcs", "total")},
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
