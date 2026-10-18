from django.contrib import admin

from sales.admin import ReadOnlyAdmin

from .models import FuelPurchase, PurchaseLine, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "phone", "is_active")
    list_filter = ("business", "is_active")


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 0
    can_delete = False
    fields = readonly_fields = ("product", "invoiced_litres", "purchase_rate")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FuelPurchase)
class FuelPurchaseAdmin(ReadOnlyAdmin):
    list_display = ("invoice_number", "supplier", "product_codes", "outlet", "delivery_date", "invoice_amount")
    list_filter = ("business",)
    inlines = [PurchaseLineInline]
