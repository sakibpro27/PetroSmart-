"""
Dealer set-up screens: business profile, outlets, products, and each outlet's
dispensers, nozzles, shifts and prices. Managers cannot open these screens.
"""

from django.db.models import Count, Q
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from core.crud import AuditedFormViewMixin, OutletScopedFormViewMixin, TenantFormViewMixin
from tenants.models import Business, Outlet
from tenants.permissions import DealerRequiredMixin

from .forms import (
    BusinessProfileForm, DispenserForm, FuelPriceForm, FuelProductForm, NozzleForm, OutletForm, ShiftForm, TankForm,
)
from .models import Dispenser, FuelPrice, FuelProduct, Nozzle, Shift, Tank

# --- Business profile -------------------------------------------------------


class BusinessProfileView(DealerRequiredMixin, TemplateView):
    template_name = "station/business_profile.html"


class BusinessProfileEditView(DealerRequiredMixin, AuditedFormViewMixin, UpdateView):
    model = Business
    form_class = BusinessProfileForm
    page_title = "Edit business profile"
    success_url = reverse_lazy("station:business")

    def get_object(self, queryset=None):
        return self.request.business


# --- Outlets ----------------------------------------------------------------


class OutletListView(DealerRequiredMixin, ListView):
    template_name = "station/outlet_list.html"
    context_object_name = "outlets"

    def get_queryset(self):
        return (
            Outlet.objects.for_business(self.request.business)
            .annotate(
                nozzle_count=Count("nozzles", filter=Q(nozzles__is_active=True), distinct=True),
                shift_count=Count("shifts", filter=Q(shifts__is_active=True), distinct=True),
            )
            .order_by("-is_active", "name")
        )


class OutletDetailView(DealerRequiredMixin, DetailView):
    """One outlet's set-up: prices, dispensers and nozzles, shifts."""

    template_name = "station/outlet_detail.html"
    context_object_name = "outlet"

    def get_queryset(self):
        return Outlet.objects.for_business(self.request.business)

    @staticmethod
    def _tanks_with_stock(business, outlet):
        from stock.services import book_stock  # the stock app builds on station

        tanks = list(Tank.objects.for_business(business).filter(outlet=outlet).select_related("product")
                     .annotate(nozzle_count=Count("nozzles", filter=Q(nozzles__is_active=True))))
        for tank in tanks:
            tank.stock_now = book_stock(tank)["stock"]
        return tanks

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        outlet, business = self.object, self.request.business
        today = timezone.localdate()

        price_rows = []
        for product in FuelProduct.objects.for_business(business).filter(is_active=True):
            upcoming = (
                FuelPrice.objects.filter(outlet=outlet, product=product, effective_from__gt=today)
                .order_by("effective_from")
                .first()
            )
            price_rows.append(
                {"product": product, "current": FuelPrice.price_on(outlet, product, today), "upcoming": upcoming}
            )

        context.update(
            price_rows=price_rows,
            price_history=FuelPrice.objects.filter(outlet=outlet).select_related("product")[:10],
            dispensers=Dispenser.objects.for_business(business).filter(outlet=outlet),
            nozzles=Nozzle.objects.for_business(business).filter(outlet=outlet).select_related("dispenser", "product", "tank"),
            tanks=self._tanks_with_stock(business, outlet),
            shifts=Shift.objects.for_business(business).filter(outlet=outlet),
        )
        return context


class OutletCreateView(TenantFormViewMixin, CreateView):
    model = Outlet
    form_class = OutletForm

    def get_success_url(self):
        return self.object.get_setup_url()

    def get_cancel_url(self):
        return reverse("station:outlet_list")


class OutletUpdateView(TenantFormViewMixin, UpdateView):
    model = Outlet
    form_class = OutletForm

    def get_success_url(self):
        return self.object.get_setup_url()


# --- Products ---------------------------------------------------------------


class ProductListView(DealerRequiredMixin, ListView):
    template_name = "station/product_list.html"
    context_object_name = "products"

    def get_queryset(self):
        return (
            FuelProduct.objects.for_business(self.request.business)
            .annotate(nozzle_count=Count("nozzles", filter=Q(nozzles__is_active=True)))
            .order_by("-is_active", "category", "code")
        )


class ProductCreateView(TenantFormViewMixin, CreateView):
    model = FuelProduct
    form_class = FuelProductForm
    page_title = "Add fuel product"
    success_url = reverse_lazy("station:product_list")


class ProductUpdateView(TenantFormViewMixin, UpdateView):
    model = FuelProduct
    form_class = FuelProductForm
    page_title = "Edit fuel product"
    success_url = reverse_lazy("station:product_list")


# --- Outlet equipment, shifts and prices -----------------------------------


class DispenserCreateView(OutletScopedFormViewMixin, CreateView):
    model = Dispenser
    form_class = DispenserForm


class DispenserUpdateView(OutletScopedFormViewMixin, UpdateView):
    model = Dispenser
    form_class = DispenserForm


class NozzleCreateView(OutletScopedFormViewMixin, CreateView):
    model = Nozzle
    form_class = NozzleForm


class NozzleUpdateView(OutletScopedFormViewMixin, UpdateView):
    model = Nozzle
    form_class = NozzleForm


class TankCreateView(OutletScopedFormViewMixin, CreateView):
    model = Tank
    form_class = TankForm


class TankUpdateView(OutletScopedFormViewMixin, UpdateView):
    model = Tank
    form_class = TankForm


class ShiftCreateView(OutletScopedFormViewMixin, CreateView):
    model = Shift
    form_class = ShiftForm


class ShiftUpdateView(OutletScopedFormViewMixin, UpdateView):
    model = Shift
    form_class = ShiftForm


class PriceCreateView(OutletScopedFormViewMixin, CreateView):
    model = FuelPrice
    form_class = FuelPriceForm
    page_title = "Set selling price"

    def get_initial(self):
        return {"effective_from": timezone.localdate()}


class PriceUpdateView(OutletScopedFormViewMixin, UpdateView):
    model = FuelPrice
    form_class = FuelPriceForm
    page_title = "Edit selling price"
