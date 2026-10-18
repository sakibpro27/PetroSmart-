from django.contrib import admin

from sales.admin import ReadOnlyAdmin

from .models import FuelPurchase, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "phone", "is_active")
    list_filter = ("business", "is_active")


@admin.register(FuelPurchase)
class FuelPurchaseAdmin(ReadOnlyAdmin):
    list_display = ("invoice_number", "supplier", "product", "outlet", "delivery_date", "invoiced_litres", "invoice_amount")
    list_filter = ("business",)
