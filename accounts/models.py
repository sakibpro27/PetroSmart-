"""
User accounts.

There are two kinds of users:

* Business users (Dealer or Manager) - always linked to exactly one Business.
* Platform administrators (the SaaS provider) - Django superusers/staff with
  no Business. They manage tenants through the platform admin site and never
  use the business screens.

The database itself enforces this split with a check constraint, so a bug in
a form cannot create a business user without a tenant or give a business user
platform-admin access.
"""

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from tenants.models import Outlet


class User(AbstractUser):
    class Role(models.TextChoices):
        DEALER = "DEALER", "Dealer"
        MANAGER = "MANAGER", "Manager"

    business = models.ForeignKey(
        "tenants.Business",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
        help_text="Leave empty only for platform administrators.",
    )
    role = models.CharField(max_length=10, choices=Role.choices, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    assigned_outlets = models.ManyToManyField(
        Outlet,
        blank=True,
        related_name="managers",
        help_text="Outlets a manager may work on. Dealers can access every outlet.",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="business_user_or_platform_admin",
                condition=(
                    # Platform admin: no business, no role.
                    Q(business__isnull=True, role="")
                    # Business user: business + valid role, never staff/superuser.
                    | Q(
                        business__isnull=False,
                        role__in=["DEALER", "MANAGER"],
                        is_staff=False,
                        is_superuser=False,
                    )
                ),
            ),
        ]

    def clean(self):
        super().clean()
        if self.business_id:
            if self.role not in (self.Role.DEALER, self.Role.MANAGER):
                raise ValidationError({"role": "Business users must be a Dealer or a Manager."})
            if self.is_staff or self.is_superuser:
                raise ValidationError("Business users cannot be platform administrators.")
        elif self.role:
            raise ValidationError({"business": "A Dealer or Manager must belong to a business."})

    @property
    def is_business_user(self):
        return self.business_id is not None

    @property
    def is_dealer(self):
        return self.is_business_user and self.role == self.Role.DEALER

    @property
    def is_manager(self):
        return self.is_business_user and self.role == self.Role.MANAGER

    def accessible_outlets(self):
        """Outlets this user may work with, always limited to their own business."""
        if not self.is_business_user:
            return Outlet.objects.none()
        outlets = Outlet.objects.for_business(self.business).filter(is_active=True)
        if self.is_manager:
            outlets = outlets.filter(pk__in=self.assigned_outlets.values("pk"))
        return outlets
