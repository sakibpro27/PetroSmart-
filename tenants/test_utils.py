"""Helpers that build realistic tenants for the automated tests."""

from datetime import timedelta

from django.utils import timezone

from accounts.models import User
from tenants.models import Business, Outlet, SubscriptionPlan

TEST_PASSWORD = "Test-Password-2026"


def make_plan(code="starter"):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        code=code, defaults={"name": code.title(), "max_outlets": 5, "max_users": 10}
    )
    return plan


def make_business(name, *, status=Business.Status.ACTIVE, days_left=180):
    today = timezone.localdate()
    return Business.objects.create(
        name=name,
        plan=make_plan(),
        status=status,
        subscription_starts_on=today - timedelta(days=30),
        subscription_ends_on=today + timedelta(days=days_left),
    )


def make_outlet(business, code, name=None):
    return Outlet.objects.create(business=business, code=code, name=name or f"{business.name} {code}")


def make_user(username, business, role):
    return User.objects.create_user(
        username=username, password=TEST_PASSWORD, business=business, role=role,
        email=f"{username}@example.com",
    )
