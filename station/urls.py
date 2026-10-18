from django.urls import path

from . import views

app_name = "station"

urlpatterns = [
    path("business/", views.BusinessProfileView.as_view(), name="business"),
    path("business/edit/", views.BusinessProfileEditView.as_view(), name="business_edit"),

    path("outlets/", views.OutletListView.as_view(), name="outlet_list"),
    path("outlets/new/", views.OutletCreateView.as_view(), name="outlet_create"),
    path("outlets/<int:pk>/", views.OutletDetailView.as_view(), name="outlet_detail"),
    path("outlets/<int:pk>/edit/", views.OutletUpdateView.as_view(), name="outlet_edit"),

    path("outlets/<int:outlet_pk>/dispensers/new/", views.DispenserCreateView.as_view(), name="dispenser_create"),
    path("dispensers/<int:pk>/edit/", views.DispenserUpdateView.as_view(), name="dispenser_edit"),
    path("outlets/<int:outlet_pk>/nozzles/new/", views.NozzleCreateView.as_view(), name="nozzle_create"),
    path("nozzles/<int:pk>/edit/", views.NozzleUpdateView.as_view(), name="nozzle_edit"),
    path("outlets/<int:outlet_pk>/tanks/new/", views.TankCreateView.as_view(), name="tank_create"),
    path("tanks/<int:pk>/edit/", views.TankUpdateView.as_view(), name="tank_edit"),
    path("outlets/<int:outlet_pk>/shifts/new/", views.ShiftCreateView.as_view(), name="shift_create"),
    path("shifts/<int:pk>/edit/", views.ShiftUpdateView.as_view(), name="shift_edit"),
    path("outlets/<int:outlet_pk>/prices/new/", views.PriceCreateView.as_view(), name="price_create"),
    path("prices/<int:pk>/edit/", views.PriceUpdateView.as_view(), name="price_edit"),

    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/new/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<int:pk>/edit/", views.ProductUpdateView.as_view(), name="product_edit"),
]
