from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [

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
