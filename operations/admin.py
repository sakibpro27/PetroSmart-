from django.contrib import admin

from sales.admin import ReadOnlyAdmin

from .models import Employee, Reminder, ShopItem, StockMovement


@admin.register(ShopItem)
class ShopItemAdmin(ReadOnlyAdmin):
    list_display = ("name", "category", "business", "is_active")
    list_filter = ("business",)


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ("moved_on", "item", "kind", "quantity", "outlet", "business")
    list_filter = ("business", "kind")


@admin.register(Employee)
class EmployeeAdmin(ReadOnlyAdmin):
    list_display = ("name", "outlet", "job_title", "is_active", "business")
    list_filter = ("business",)


@admin.register(Reminder)
class ReminderAdmin(ReadOnlyAdmin):
    list_display = ("title", "due_date", "completed_on", "business")
    list_filter = ("business", "category")
