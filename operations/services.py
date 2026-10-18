"""Rules for shop stock, attendance and reminders, with audit logging."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from audit.models import AuditLog
from sales.services import viewable_outlets

from .models import Attendance, Employee, Reminder, ShopItem, StockMovement, add_months

ZERO = Decimal("0")
DUE_SOON_DAYS = 30


def _require_outlet(user, outlet):
    if not user.accessible_outlets().filter(pk=outlet.pk).exists():
        raise PermissionDenied("You are not assigned to this outlet.")


def _require_dealer(user):
    if not user.is_dealer:
        raise PermissionDenied("Only the Dealer can do this.")


# --- Shop stock -------------------------------------------------------------------


def stock_table(user, outlets):
    """Rows of (item, outlet, quantity on hand, low?) for active items at the given outlets."""
    totals = {
        (row["item"], row["outlet"]): row["total"]
        for row in StockMovement.objects.filter(business=user.business, outlet__in=outlets)
        .values("item", "outlet").annotate(total=Sum("quantity"))
    }
    rows = []
    for item in ShopItem.objects.for_business(user.business).filter(is_active=True):
        for outlet in outlets:
            on_hand = totals.get((item.pk, outlet.pk), ZERO)
            rows.append({"item": item, "outlet": outlet, "on_hand": on_hand, "low": on_hand <= item.reorder_level})
    return rows


@transaction.atomic
def record_movement(form, *, user, request=None):
    """
    Save a stock movement. The form gives a positive quantity; sales are
    stored as negative. Sales and negative adjustments cannot take stock below zero.
    """
    movement = form.save(commit=False)
    _require_outlet(user, movement.outlet)
    if movement.moved_on > timezone.localdate():
        raise ValidationError("A stock movement cannot be dated in the future.")
    if movement.kind == StockMovement.Kind.SALE:
        movement.quantity = -abs(movement.quantity)
    if movement.quantity < 0:
        # Lock the item so two sales cannot both use the last units.
        ShopItem.objects.select_for_update().get(pk=movement.item_id)
        on_hand = movement.item.stock_at(movement.outlet)
        if on_hand + movement.quantity < 0:
            raise ValidationError(f"Only {on_hand:.2f} {movement.item.get_unit_display().lower()}(s) of {movement.item} "
                                  f"are in stock at {movement.outlet.code}.")
    movement.entered_by = user
    movement.full_clean()
    movement.save()
    AuditLog.record(AuditLog.Action.CREATE, f"{movement.get_kind_display()}: {abs(movement.quantity)} × {movement.item} "
                    f"at {movement.outlet.code}", user=user, obj=movement,
                    changes={"quantity": str(movement.quantity),
                             "unit_price": None if movement.unit_price is None else str(movement.unit_price)},
                    request=request)
    return movement


def shop_sales(user, outlets, date_from, date_to):
    """Shop sales value for a period: kept separate from fuel sales."""
    sales = StockMovement.objects.filter(business=user.business, outlet__in=outlets, kind=StockMovement.Kind.SALE,
                                         moved_on__range=(date_from, date_to)).select_related("item")
    return sum((m.amount or ZERO for m in sales), ZERO)


# --- Attendance -----------------------------------------------------------------------


@transaction.atomic
def save_attendance(*, user, shift, work_date, entries, request=None):
    """`entries` is a list of (employee, status, duty) for one outlet, date and shift."""
    _require_outlet(user, shift.outlet)
    if work_date > timezone.localdate():
        raise ValidationError("Attendance cannot be recorded for a future date.")
    for employee, status, duty in entries:
        if employee.outlet_id != shift.outlet_id or employee.business_id != user.business_id:
            raise ValidationError(f"{employee} does not work at {shift.outlet.code}.")
        Attendance.objects.update_or_create(
            business=user.business, employee=employee, shift=shift, work_date=work_date,
            defaults={"status": status, "duty": duty, "entered_by": user},
        )
    AuditLog.record(AuditLog.Action.UPDATE, f"Attendance for {shift.outlet.code} {work_date:%d-%m-%Y} {shift.name}",
                    user=user, changes={e.name: s for e, s, _ in entries}, request=request)


# --- Reminders -------------------------------------------------------------------------


def reminders_for(user):
    outlets = viewable_outlets(user)
    return Reminder.objects.for_business(user.business).filter(Q(outlet__isnull=True) | Q(outlet__in=outlets))


def due_reminders(user, today=None):
    """Open reminders that are overdue or due within DUE_SOON_DAYS days."""
    today = today or timezone.localdate()
    return reminders_for(user).filter(completed_on__isnull=True, due_date__lte=today + timedelta(days=DUE_SOON_DAYS)) \
        .select_related("outlet").order_by("due_date")


@transaction.atomic
def complete_reminder(reminder, *, user, note="", request=None):
    _require_dealer(user)
    reminder = Reminder.objects.select_for_update().get(pk=reminder.pk)
    if reminder.completed_on:
        raise ValidationError("This reminder is already marked done.")
    reminder.completed_on, reminder.completed_by, reminder.completion_note = timezone.localdate(), user, note.strip()
    reminder.save()
    following = None
    if reminder.repeat_months:
        following = Reminder.objects.create(
            business=reminder.business, outlet=reminder.outlet, title=reminder.title, category=reminder.category,
            due_date=add_months(reminder.due_date, reminder.repeat_months), repeat_months=reminder.repeat_months,
            notes=reminder.notes,
        )
    AuditLog.record(AuditLog.Action.UPDATE, f"Completed reminder '{reminder.title}'", user=user, obj=reminder,
                    changes={"note": reminder.completion_note,
                             "next_due": None if following is None else str(following.due_date)},
                    request=request)
    return following
