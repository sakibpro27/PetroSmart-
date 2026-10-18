from django.contrib import admin

from sales.admin import ReadOnlyAdmin

from .models import StockLine, StockSheet, TankReceipt


class StockLineInline(admin.TabularInline):
    model = StockLine
    extra = 0
    can_delete = False
    fields = readonly_fields = ("tank", "opening_stock", "fuel_received", "total_delivery", "testing_litres",
                                "calculated_closing", "measured_closing", "variation", "notes")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(StockSheet)
class StockSheetAdmin(ReadOnlyAdmin):
    list_display = ("business_date", "outlet", "entered_by", "business")
    list_filter = ("business",)
    inlines = [StockLineInline]


@admin.register(TankReceipt)
class TankReceiptAdmin(ReadOnlyAdmin):
    list_display = ("received_on", "tank", "litres", "reference", "outlet", "business")
    list_filter = ("business",)
