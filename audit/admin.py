from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only view for the platform administrator."""

    list_display = ("created_at", "business", "user", "action", "description", "ip_address")
    list_filter = ("action", "business")
    search_fields = ("description", "user__username", "business__name")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
