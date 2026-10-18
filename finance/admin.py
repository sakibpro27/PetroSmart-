from django.contrib import admin

from sales.admin import ReadOnlyAdmin

from .models import CreditCustomer, CustomerPayment, Expense, ShiftCollection


@admin.register(ShiftCollection)
class ShiftCollectionAdmin(ReadOnlyAdmin):
    list_display = ("business_date", "outlet", "shift", "status", "business")
    list_filter = ("status", "business")


@admin.register(CreditCustomer)
class CreditCustomerAdmin(ReadOnlyAdmin):
    list_display = ("name", "business", "credit_limit", "is_active")
    list_filter = ("business",)


@admin.register(CustomerPayment)
class CustomerPaymentAdmin(ReadOnlyAdmin):
    list_display = ("received_on", "customer", "amount", "business")
    list_filter = ("business",)


@admin.register(Expense)
class ExpenseAdmin(ReadOnlyAdmin):
    list_display = ("expense_date", "description", "category", "amount", "outlet", "business")
    list_filter = ("business",)
