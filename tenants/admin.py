from django.contrib import admin, messages

from .models import Business, Outlet, SubscriptionPlan, SubscriptionRenewal
from .services import renew


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "max_outlets", "max_users", "price_per_year", "is_active")
    prepopulated_fields = {"code": ("name",)}


class OutletInline(admin.TabularInline):
    model = Outlet
    extra = 0
    fields = ("name", "code", "oil_company", "is_active")


class RenewalInline(admin.TabularInline):
    model = SubscriptionRenewal
    extra = 0
    can_delete = False
    fields = readonly_fields = ("created_at", "plan", "previous_end", "new_end", "amount", "reference", "recorded_by")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "plan", "status", "subscription_ends_on", "days_left", "has_access")
    list_filter = ("status", "plan")
    search_fields = ("name", "legal_name", "contact_email", "contact_phone")
    inlines = [OutletInline, RenewalInline]
    actions = ["renew_12_months", "suspend"]

    @admin.display(boolean=True, description="Access")
    def has_access(self, obj):
        return obj.has_access

    @admin.display(description="Days left")
    def days_left(self, obj):
        return obj.days_remaining

    @admin.action(description="Renew selected subscriptions for 12 months")
    def renew_12_months(self, request, queryset):
        for business in queryset:
            renewal = renew(business, months=12, recorded_by=request.user, request=request)
            self.message_user(request, f"{business.name}: valid until {renewal.new_end:%d %b %Y}.", messages.SUCCESS)

    @admin.action(description="Suspend selected businesses")
    def suspend(self, request, queryset):
        updated = queryset.update(status=Business.Status.SUSPENDED)
        self.message_user(request, f"{updated} business(es) suspended. Their users can no longer use PetroSmart.",
                          messages.WARNING)


@admin.register(Outlet)
class OutletAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "business", "oil_company", "is_active")
    list_filter = ("business", "is_active")
    search_fields = ("name", "code", "business__name")


@admin.register(SubscriptionRenewal)
class SubscriptionRenewalAdmin(admin.ModelAdmin):
    list_display = ("business", "previous_end", "new_end", "amount", "reference", "recorded_by", "created_at")
    list_filter = ("business",)
    readonly_fields = ("business", "plan", "previous_end", "new_end", "recorded_by", "created_at")

    def has_add_permission(self, request):
        return False  # renewals are created by the "Renew" action so the business is updated too

    def has_delete_permission(self, request, obj=None):
        return False
