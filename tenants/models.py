"""
Tenant (customer business) models.

Every piece of business data in PetroSmart belongs to exactly one Business.
Models that hold business data inherit from TenantOwnedModel, and views must
fetch them through `Model.objects.for_business(request.business)` so that a
user can never read or change another dealer's records.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone


class SubscriptionPlan(models.Model):
    """A plan sold by the SaaS provider (e.g. Starter, Multi-Outlet)."""

    name = models.CharField(max_length=60, unique=True)
    code = models.SlugField(max_length=30, unique=True)
    max_outlets = models.PositiveIntegerField(default=1)
    max_users = models.PositiveIntegerField(default=3)
    price_per_year = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True, help_text="Inactive plans cannot be sold.")

    class Meta:
        ordering = ["price_per_year", "name"]

    def __str__(self):
        return self.name


class Business(models.Model):
    """A petrol pump dealer's business account. This is the tenant."""

    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Trial"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        CANCELLED = "CANCELLED", "Cancelled"

    name = models.CharField(max_length=150)
    legal_name = models.CharField(max_length=200, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="businesses")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRIAL)
    subscription_starts_on = models.DateField(default=timezone.localdate)
    subscription_ends_on = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "businesses"

    def __str__(self):
        return self.name

    def clean(self):
        if self.subscription_ends_on and self.subscription_starts_on:
            if self.subscription_ends_on < self.subscription_starts_on:
                raise ValidationError(
                    {"subscription_ends_on": "End date cannot be before the start date."}
                )
        if self.pk and self.plan_id:
            # A plan change must not leave the business over its new limits.
            active_outlets = Outlet.objects.filter(business=self, is_active=True).count()
            active_users = self.users.filter(is_active=True).count()
            errors = []
            if active_outlets > self.plan.max_outlets:
                errors.append(f"The {self.plan.name} plan allows {self.plan.max_outlets} active outlet(s); "
                              f"this business has {active_outlets}.")
            if active_users > self.plan.max_users:
                errors.append(f"The {self.plan.name} plan allows {self.plan.max_users} active user(s); "
                              f"this business has {active_users}.")
            if errors:
                raise ValidationError({"plan": errors})

    @property
    def is_subscription_current(self):
        return timezone.localdate() <= self.subscription_ends_on

    @property
    def has_access(self):
        """True when users of this business may use the application."""
        return (
            self.status in (self.Status.TRIAL, self.Status.ACTIVE)
            and self.is_subscription_current
        )

    @property
    def days_remaining(self):
        return (self.subscription_ends_on - timezone.localdate()).days


class SubscriptionRenewal(models.Model):
    """
    A record of each renewal or plan change made by the platform administrator.
    Payment collection happens outside PetroSmart; this keeps the history.
    """

    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="renewals")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="+")
    previous_end = models.DateField()
    new_end = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Amount received (₹), if any.")
    reference = models.CharField(max_length=100, blank=True, help_text="Invoice or payment reference.")
    recorded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.business}: {self.previous_end:%d-%m-%Y} → {self.new_end:%d-%m-%Y}"


class TenantQuerySet(models.QuerySet):
    def for_business(self, business):
        """The only approved way to list tenant data in a view."""
        if business is None:
            return self.none()
        return self.filter(business=business)


class TenantOwnedModel(models.Model):
    """Abstract base for every model that stores a dealer's business data."""

    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="+")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


class Outlet(TenantOwnedModel):
    """A single petrol pump site belonging to a business."""

    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=20, help_text="Short code used on reports, e.g. OUT-01."
    )
    address = models.TextField(blank=True)
    oil_company = models.CharField(
        max_length=60, blank=True, help_text="e.g. IOCL, BPCL, HPCL, Nayara, Jio-bp."
    )
    # Printed at the top of credit bills.
    gstin = models.CharField("GSTIN", max_length=15, blank=True)
    phone = models.CharField("mobile", max_length=20, blank=True)
    email = models.EmailField(blank=True)
    bill_terms = models.TextField(
        "terms and conditions on bills", blank=True,
        help_text="Printed at the bottom of every credit bill. One condition per line.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    OIL_COMPANY_NAMES = {
        "IOCL": "Indian Oil Corporation Ltd.", "IOC": "Indian Oil Corporation Ltd.",
        "BPCL": "Bharat Petroleum Corporation Ltd.", "HPCL": "Hindustan Petroleum Corporation Ltd.",
        "NAYARA": "Nayara Energy Ltd.", "JIO-BP": "Jio-bp", "SHELL": "Shell India Markets Pvt. Ltd.",
    }

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"],
                name="unique_outlet_code_per_business",
                violation_error_message="Another outlet in your business already uses this code.",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def oil_company_full_name(self):
        """'BPCL' -> 'Bharat Petroleum Corporation Ltd.' for the bill heading; other names are shown as typed."""
        return self.OIL_COMPANY_NAMES.get(self.oil_company.strip().upper(), self.oil_company.strip())

    def get_setup_url(self):
        return reverse("station:outlet_detail", args=[self.pk])
