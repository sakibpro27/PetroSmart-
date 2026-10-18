from django.contrib import admin

from .models import Dispenser, FuelPrice, FuelProduct, Nozzle, Shift, Tank


@admin.register(FuelProduct)
class FuelProductAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "business", "is_active")
    list_filter = ("category", "is_active", "business")


@admin.register(FuelPrice)
class FuelPriceAdmin(admin.ModelAdmin):
    list_display = ("product", "outlet", "effective_from", "price_per_litre", "business")
    list_filter = ("business",)


@admin.register(Dispenser)
class DispenserAdmin(admin.ModelAdmin):
    list_display = ("code", "outlet", "make", "is_active", "business")
    list_filter = ("business", "is_active")


@admin.register(Nozzle)
class NozzleAdmin(admin.ModelAdmin):
    list_display = ("code", "outlet", "dispenser", "product", "initial_reading", "is_active", "business")
    list_filter = ("business", "is_active")


@admin.register(Tank)
class TankAdmin(admin.ModelAdmin):
    list_display = ("code", "outlet", "product", "capacity_litres", "is_active", "business")
    list_filter = ("business", "is_active")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("name", "outlet", "start_time", "end_time", "sort_order", "is_active", "business")
    list_filter = ("business", "is_active")
