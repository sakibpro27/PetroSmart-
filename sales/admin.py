from django.contrib import admin

from .models import CorrectionLine, DailySalesLine, DailySalesSheet, SalesCorrection


class ReadOnlyAdmin(admin.ModelAdmin):
    """
    Platform administrators may inspect business records for support, but not
    change them: changes go through the business screens so that history is kept.
    """

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class LineInline(admin.TabularInline):
    model = DailySalesLine
    extra = 0
    can_delete = False
    readonly_fields = ("nozzle", "product", "opening_reading", "closing_reading", "testing_litres",
                       "price_per_litre", "total_delivery", "net_sales_litres", "sales_value", "meter_reset")
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DailySalesSheet)
class DailySalesSheetAdmin(ReadOnlyAdmin):
    list_display = ("business_date", "outlet", "shift", "dispenser", "employee", "business")
    list_filter = ("business",)
    inlines = [LineInline]


@admin.register(SalesCorrection)
class SalesCorrectionAdmin(ReadOnlyAdmin):
    list_display = ("sheet", "requested_by", "requested_at")
    list_filter = ("business",)


admin.site.register(CorrectionLine, ReadOnlyAdmin)
