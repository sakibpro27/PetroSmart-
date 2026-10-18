"""
Figures for the dashboard. Every query is limited to the business and to the
outlets the user may see.

"Today's" sales include sheets that are submitted or approved (not drafts), so
a manager's figures appear before the Dealer approves them. The dashboard says
so, and shows how many are still awaiting approval.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum

from finance.models import CollectionLine, CreditSale, Expense
from finance.services import outstanding_total
from purchases.models import FuelPurchase
from sales.models import DailySalesLine, DailySalesSheet, SalesCorrection
from station.models import FuelProduct, Tank
from stock.models import StockLine, StockSheet

ZERO = Decimal("0")
COUNTED = (DailySalesSheet.Status.SUBMITTED, DailySalesSheet.Status.APPROVED)
CHART_DAYS = 14


def _sum(qs, field):
    return qs.aggregate(total=Sum(field))["total"] or ZERO


def sales_by_category(business, outlets, day):
    lines = DailySalesLine.objects.filter(business=business, sheet__outlet__in=outlets, sheet__business_date=day,
                                          sheet__status__in=COUNTED, closing_reading__isnull=False)
    result = {}
    for category, label in FuelProduct.Category.choices:
        subset = lines.filter(product__category=category)
        result[category] = {
            "label": label,
            "total_delivery": _sum(subset, "total_delivery"),
            "testing_litres": _sum(subset, "testing_litres"),
            "net_sales_litres": _sum(subset, "net_sales_litres"),
            "sales_value": _sum(subset, "sales_value"),
        }
    totals = {key: sum((row[key] for row in result.values()), ZERO)
              for key in ("total_delivery", "testing_litres", "net_sales_litres", "sales_value")}
    return result, totals


def daily_chart(business, outlets, day):
    """Net customer sales litres per day for the last CHART_DAYS days, MS and HSD separately."""
    start = day - timedelta(days=CHART_DAYS - 1)
    rows = (
        DailySalesLine.objects.filter(business=business, sheet__outlet__in=outlets,
                                      sheet__business_date__range=(start, day), sheet__status__in=COUNTED,
                                      closing_reading__isnull=False)
        .values("sheet__business_date", "product__category").annotate(net=Sum("net_sales_litres"))
    )
    lookup = {(row["sheet__business_date"], row["product__category"]): row["net"] or ZERO for row in rows}
    days = [start + timedelta(days=i) for i in range(CHART_DAYS)]
    return {
        "labels": [d.strftime("%d %b") for d in days],
        "ms": [float(lookup.get((d, "MS"), ZERO)) for d in days],
        "hsd": [float(lookup.get((d, "HSD"), ZERO)) for d in days],
        "rows": [{"date": d, "ms": lookup.get((d, "MS"), ZERO), "hsd": lookup.get((d, "HSD"), ZERO)} for d in days],
    }


def tank_stock(business, outlets):
    """Each active tank's latest measured (dip) stock."""
    tanks = Tank.objects.filter(business=business, outlet__in=outlets, is_active=True).select_related("outlet", "product")
    result = []
    for tank in tanks:
        line = (StockLine.objects.filter(tank=tank, measured_closing__isnull=False)
                .select_related("sheet").order_by("-sheet__business_date").first())
        measured = line.measured_closing if line else None
        result.append({
            "tank": tank, "measured": measured, "as_of": line.sheet.business_date if line else None,
            "percent": int(measured * 100 / tank.capacity_litres) if measured is not None else None,
        })
    return result


def payments(business, outlets, day):
    lines = CollectionLine.objects.filter(business=business, collection__outlet__in=outlets,
                                          collection__business_date=day)
    rows = list(lines.values("method__name").annotate(total=Sum("amount")).order_by("method__sort_order"))
    credit = _sum(CreditSale.objects.filter(business=business, collection__outlet__in=outlets,
                                            collection__business_date=day), "amount")
    return {"rows": rows, "credit": credit,
            "chart": {"labels": [r["method__name"] for r in rows] + ["Credit sales"],
                      "values": [float(r["total"] or 0) for r in rows] + [float(credit)]}}


def exceptions(business, outlets, day):
    since = day - timedelta(days=30)
    flagged = [
        line for line in StockLine.objects.filter(
            business=business, sheet__outlet__in=outlets, sheet__business_date__range=(since, day),
            variation__isnull=False,
        ).select_related("tank", "sheet__outlet").order_by("-sheet__business_date")
        if line.is_flagged
    ][:8]
    resets = (DailySalesLine.objects.filter(business=business, sheet__outlet__in=outlets, meter_reset=True,
                                            sheet__business_date__range=(since, day))
              .select_related("nozzle", "sheet__outlet", "sheet__shift").order_by("-sheet__business_date")[:8])
    return {"flagged_stock": flagged, "meter_resets": list(resets)}


def pending(business, outlets):
    sheets = DailySalesSheet.objects.filter(business=business, outlet__in=outlets)
    return {
        "sales_drafts": sheets.filter(status=DailySalesSheet.Status.DRAFT).count(),
        "sales_submitted": sheets.filter(status=DailySalesSheet.Status.SUBMITTED).count(),
        "corrections": SalesCorrection.objects.filter(business=business, sheet__outlet__in=outlets,
                                                      status=SalesCorrection.Status.PENDING).count(),
        "stock_submitted": StockSheet.objects.filter(business=business, outlet__in=outlets,
                                                     status=StockSheet.Status.SUBMITTED).count(),
    }


def build(user, outlets, day):
    business = user.business
    sales, totals = sales_by_category(business, outlets, day)
    month_start = day.replace(day=1)
    return {
        "day": day,
        "sales": sales,
        "totals": totals,
        "chart": daily_chart(business, outlets, day),
        "tanks": tank_stock(business, outlets),
        "deliveries": FuelPurchase.objects.filter(business=business, outlet__in=outlets)
        .select_related("supplier", "product", "outlet").order_by("-delivery_date", "-pk")[:5],
        "payments": payments(business, outlets, day),
        "month_expenses": _sum(Expense.objects.filter(business=business, outlet__in=outlets,
                                                      expense_date__range=(month_start, day)), "amount"),
        "outstanding": outstanding_total(business) if user.is_dealer else None,
        "exceptions": exceptions(business, outlets, day),
        "pending": pending(business, outlets),
        "awaiting_today": DailySalesSheet.objects.filter(business=business, outlet__in=outlets, business_date=day,
                                                         status=DailySalesSheet.Status.SUBMITTED).count(),
    }
