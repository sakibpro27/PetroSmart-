from django.urls import path

from . import views

app_name = "stock"

urlpatterns = [
    path("", views.StockSheetListView.as_view(), name="sheet_list"),
    path("new/", views.StockSheetFormView.as_view(), name="sheet_create"),
    path("<int:pk>/", views.StockSheetDetailView.as_view(), name="sheet_detail"),
    path("<int:pk>/edit/", views.StockSheetFormView.as_view(), name="sheet_edit"),
    path("<int:pk>/delete/", views.StockSheetDeleteView.as_view(), name="sheet_delete"),
    path("receipts/", views.ReceiptListView.as_view(), name="receipt_list"),
    path("receipts/new/", views.ReceiptFormView.as_view(), name="receipt_create"),
    path("receipts/<int:pk>/edit/", views.ReceiptFormView.as_view(), name="receipt_edit"),
    path("receipts/<int:pk>/delete/", views.ReceiptDeleteView.as_view(), name="receipt_delete"),
]
