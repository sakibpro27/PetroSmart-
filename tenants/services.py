"""Subscription renewal, used by the platform administration."""

import calendar
from datetime import date

from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog

from .models import Business, SubscriptionRenewal


def _add_months(day, months):
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@transaction.atomic
def renew(business, *, months, recorded_by, amount=0, reference="", request=None):
    """
    Extend a subscription by `months`. An active subscription is extended from
    its current end date (no days are lost); an expired one from today.
    """
    business = Business.objects.select_for_update().get(pk=business.pk)
    today = timezone.localdate()
    start_from = business.subscription_ends_on if business.subscription_ends_on >= today else today
    previous_end = business.subscription_ends_on
    business.subscription_ends_on = _add_months(start_from, months)
    if business.status in (Business.Status.SUSPENDED, Business.Status.TRIAL, Business.Status.CANCELLED):
        business.status = Business.Status.ACTIVE
    business.save(update_fields=["subscription_ends_on", "status", "updated_at"])
    renewal = SubscriptionRenewal.objects.create(
        business=business, plan=business.plan, previous_end=previous_end, new_end=business.subscription_ends_on,
        amount=amount, reference=reference, recorded_by=recorded_by,
    )
    AuditLog.record(AuditLog.Action.UPDATE, f"Subscription renewed until {business.subscription_ends_on:%d %b %Y}",
                    user=recorded_by, business=business, obj=renewal,
                    changes={"previous_end": str(previous_end), "new_end": str(business.subscription_ends_on),
                             "months": months}, request=request)
    return renewal
