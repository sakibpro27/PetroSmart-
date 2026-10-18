from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class PetroSmartUserAdmin(UserAdmin):
    """Platform-admin screen for creating dealer accounts and platform staff."""

    list_display = ("username", "get_full_name", "business", "role", "is_active", "is_staff", "last_login")
    list_filter = ("role", "is_active", "is_staff", "business")
    search_fields = ("username", "first_name", "last_name", "email", "business__name")
    filter_horizontal = ("assigned_outlets", "groups", "user_permissions")

    fieldsets = UserAdmin.fieldsets + (
        ("PetroSmart business access", {"fields": ("business", "role", "phone", "assigned_outlets")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("PetroSmart business access", {"fields": ("business", "role", "phone")}),
    )

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        # Only offer outlets from the user's own business when editing.
        if db_field.name == "assigned_outlets":
            object_id = request.resolver_match.kwargs.get("object_id")
            user = User.objects.filter(pk=object_id).first() if object_id else None
            if user and user.business_id:
                kwargs["queryset"] = db_field.related_model.objects.for_business(user.business)
        return super().formfield_for_manytomany(db_field, request, **kwargs)
