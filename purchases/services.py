"""
Saving fuel purchases together with their tank receipts, in one transaction,
with the outlet, product and stock-lock rules checked on the server.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from audit.models import AuditLog
from sales.services import viewable_outlets
from stock.models import StockLine, TankReceipt
from stock.services import stock_locked

from .models import FuelPurchase, PurchaseLine


def purchases_for(user):
    return FuelPurchase.objects.for_business(user.business).filter(outlet__in=viewable_outlets(user))


def received_litres(purchase):
    return purchase.receipts.aggregate(total=Sum("litres"))["total"] or Decimal("0")


def is_locked(purchase):
    return stock_locked(purchase.outlet, purchase.delivery_date)


def _check_allowed(user, outlet, day):
    if not user.accessible_outlets().filter(pk=outlet.pk).exists():
        raise PermissionDenied("You are not assigned to this outlet.")
    if day > timezone.localdate():
        raise ValidationError("A delivery cannot be dated in the future.")
    if stock_locked(outlet, day):
        raise ValidationError(
            f"Tank stock for {outlet.code} on {day:%d %b %Y} is already saved, so deliveries on that date are locked."
        )


@transaction.atomic
def save_purchase(form, lines, allocations, *, user, request=None):
    """
    `form` is a valid PurchaseForm, `lines` a list of (product, invoiced_litres,
    rate) - one per product on the invoice, so MS and HSD can share an invoice -
    and `allocations` a list of (tank, litres) received into each tank.
    Existing product lines and receipts are replaced.
    """
    purchase = form.instance
    is_new = purchase.pk is None
    if not is_new:
        original = FuelPurchase.objects.select_related("outlet").get(pk=purchase.pk)
        _check_allowed(user, original.outlet, original.delivery_date)
    outlet, day = form.cleaned_data["outlet"], form.cleaned_data["delivery_date"]
    _check_allowed(user, outlet, day)

    if not lines:
        raise ValidationError("Enter at least one product with its invoiced quantity and rate.")
    products = {product.pk: product for product, _litres, _rate in lines}
    if len(products) != len(lines):
        raise ValidationError("Each product can appear only once on an invoice. Add the litres together instead.")
    if not allocations:
        raise ValidationError("Allocate the received litres to at least one tank.")
    for tank, _litres in allocations:
        if tank.outlet_id != outlet.pk:
            raise ValidationError(f"Tank {tank.code} is at {tank.outlet.code}, not at {outlet.code}.")
        if tank.product_id not in products:
            raise ValidationError(f"Tank {tank.code} holds {tank.product.name}, which is not on this invoice.")
    if len({tank.pk for tank, _ in allocations}) != len(allocations):
        raise ValidationError("Each tank can appear only once. Add the litres together instead.")
    received_products = {tank.product_id for tank, _ in allocations}
    missing = [p.name for pk, p in products.items() if pk not in received_products]
    if missing:
        raise ValidationError(f"Allocate the received litres of {', '.join(missing)} to a tank.")

    purchase = form.save(commit=False)
    if is_new:
        purchase.entered_by = user
    purchase.save()
    old_lines = {l.product.code: f"{l.invoiced_litres:.2f} @ {l.purchase_rate}" for l in purchase.lines.select_related("product")}
    purchase.lines.all().delete()
    for product, litres, rate in lines:
        PurchaseLine.objects.create(business=purchase.business, purchase=purchase, product=product,
                                    invoiced_litres=litres, purchase_rate=rate)
    new_lines = {product.code: f"{litres:.2f} @ {rate}" for product, litres, rate in lines}
    old = {r.tank.code: f"{r.litres:.2f}" for r in purchase.receipts.select_related("tank")}
    purchase.receipts.all().delete()
    for tank, litres in allocations:
        TankReceipt.objects.create(
            business=purchase.business, outlet=outlet, tank=tank, received_on=day, litres=litres,
            reference=purchase.invoice_number, purchase=purchase, entered_by=user,
            notes=f"From {purchase.supplier.name}",
        )
    new = {tank.code: f"{litres:.2f}" for tank, litres in allocations}
    changes = form.audit_changes()
    if old_lines != new_lines:
        changes["products"] = {"from": old_lines, "to": new_lines} if not is_new else new_lines
    if old != new:
        changes["tank_allocation"] = {"from": old, "to": new} if not is_new else new
    AuditLog.record(AuditLog.Action.CREATE if is_new else AuditLog.Action.UPDATE,
                    f"{'Recorded' if is_new else 'Updated'} fuel purchase {purchase}", user=user, obj=purchase,
                    changes=changes, request=request)
    return purchase


@transaction.atomic
def delete_purchase(purchase, *, user, request=None):
    _check_allowed(user, purchase.outlet, purchase.delivery_date)
    AuditLog.record(AuditLog.Action.DELETE, f"Deleted fuel purchase {purchase}", user=user, obj=purchase,
                    changes={"invoice_number": purchase.invoice_number, "supplier": str(purchase.supplier),
                             "products": {l.product.code: f"{l.invoiced_litres:.2f} @ {l.purchase_rate}"
                                          for l in purchase.lines.select_related("product")},
                             "invoice_amount": str(purchase.invoice_amount),
                             "receipts": {r.tank.code: str(r.litres) for r in purchase.receipts.select_related("tank")}},
                    request=request)
    purchase.receipts.all().delete()
    purchase.delete()


def product_comparison(purchase):
    """For each product on the invoice: invoiced litres, litres received into tanks, and the difference."""
    received = {}
    for receipt in purchase.receipts.select_related("tank"):
        received[receipt.tank.product_id] = received.get(receipt.tank.product_id, Decimal("0")) + receipt.litres
    rows = []
    for line in purchase.lines.select_related("product"):
        got = received.get(line.product_id, Decimal("0"))
        rows.append({"line": line, "received": got, "difference": got - line.invoiced_litres})
    return rows


def stock_comparison(purchase):
    """
    For each tank the delivery went into: litres received from this invoice,
    and that day's stock reconciliation line if one has been recorded.
    """
    rows = []
    for receipt in purchase.receipts.select_related("tank"):
        line = (StockLine.objects.filter(tank=receipt.tank, sheet__business_date=purchase.delivery_date)
                .select_related("sheet").first())
        rows.append({"receipt": receipt, "stock_line": line})
    return rows
