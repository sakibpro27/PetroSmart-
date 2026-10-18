from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("collections/", views.CollectionListView.as_view(), name="collection_list"),
    path("collections/new/", views.CollectionCreateView.as_view(), name="collection_create"),
    path("collections/<int:pk>/", views.CollectionDetailView.as_view(), name="collection_detail"),
    path("collections/<int:pk>/edit/", views.CollectionEditView.as_view(), name="collection_edit"),
    path("collections/<int:pk>/verify/", views.CollectionVerifyView.as_view(), name="collection_verify"),
    path("collections/<int:pk>/reopen/", views.CollectionReopenView.as_view(), name="collection_reopen"),

    path("customers/", views.CustomerListView.as_view(), name="customer_list"),
    path("customers/new/", views.CustomerCreateView.as_view(), name="customer_create"),
    path("customers/<int:pk>/", views.CustomerLedgerView.as_view(), name="customer_ledger"),
    path("customers/<int:pk>/edit/", views.CustomerUpdateView.as_view(), name="customer_edit"),
    path("customers/<int:pk>/adjust/", views.AdjustmentCreateView.as_view(), name="customer_adjust"),
    path("payments/new/", views.PaymentCreateView.as_view(), name="payment_create"),
    path("payments/<int:pk>/delete/", views.PaymentDeleteView.as_view(), name="payment_delete"),

    path("expenses/", views.ExpenseListView.as_view(), name="expense_list"),
    path("expenses/new/", views.ExpenseFormView.as_view(), name="expense_create"),
    path("expenses/<int:pk>/edit/", views.ExpenseFormView.as_view(), name="expense_edit"),
    path("expenses/<int:pk>/delete/", views.ExpenseDeleteView.as_view(), name="expense_delete"),

    path("summary/", views.OperationalSummaryView.as_view(), name="summary"),
    path("settings/", views.FinanceSettingsView.as_view(), name="settings"),
    path("settings/methods/new/", views.MethodCreateView.as_view(), name="method_create"),
    path("settings/methods/<int:pk>/edit/", views.MethodUpdateView.as_view(), name="method_edit"),
    path("settings/categories/new/", views.CategoryCreateView.as_view(), name="category_create"),
    path("settings/categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_edit"),
]
