from django.urls import path

from . import views

app_name = "stock"

urlpatterns = [
    path("", views.StockSheetListView.as_view(), name="sheet_list"),
    path("new/", views.StockSheetCreateView.as_view(), name="sheet_create"),
    path("<int:pk>/", views.StockSheetDetailView.as_view(), name="sheet_detail"),
    path("<int:pk>/edit/", views.StockSheetEditView.as_view(), name="sheet_edit"),
    path("<int:pk>/approve/", views.StockSheetApproveView.as_view(), name="sheet_approve"),
    path("<int:pk>/return/", views.StockSheetReturnView.as_view(), name="sheet_return"),
    path("receipts/", views.ReceiptListView.as_view(), name="receipt_list"),
    path("receipts/new/", views.ReceiptFormView.as_view(), name="receipt_create"),
    path("receipts/<int:pk>/edit/", views.ReceiptFormView.as_view(), name="receipt_edit"),
    path("receipts/<int:pk>/delete/", views.ReceiptDeleteView.as_view(), name="receipt_delete"),
]
