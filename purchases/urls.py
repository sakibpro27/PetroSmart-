from django.urls import path

from . import views

app_name = "purchases"

urlpatterns = [
    path("", views.PurchaseListView.as_view(), name="purchase_list"),
    path("new/", views.PurchaseFormView.as_view(), name="purchase_create"),
    path("<int:pk>/", views.PurchaseDetailView.as_view(), name="purchase_detail"),
    path("<int:pk>/edit/", views.PurchaseFormView.as_view(), name="purchase_edit"),
    path("<int:pk>/delete/", views.PurchaseDeleteView.as_view(), name="purchase_delete"),
    path("suppliers/", views.SupplierListView.as_view(), name="supplier_list"),
    path("suppliers/new/", views.SupplierCreateView.as_view(), name="supplier_create"),
    path("suppliers/<int:pk>/edit/", views.SupplierUpdateView.as_view(), name="supplier_edit"),
]
