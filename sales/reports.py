"""
Daily Sales summaries.

Each row shows total nozzle delivery, testing litres, net customer sales and
customer sales value separately. Sales litres and value come from NET sales,
so testing litres are never counted as sales. By default only APPROVED sheets
are included.
"""

from django.db.models import Sum
from django.db.models.functions import TruncMonth

from .models import DailySalesLine, DailySalesSheet

GROUPINGS = {
    "day": ("Date", ["sheet__business_date"]),
    "month": ("Month", ["month"]),
    "outlet": ("Outlet", ["sheet__outlet__code", "sheet__outlet__name"]),
    "product": ("Product", ["product__category", "product__code", "product__name"]),
    "nozzle": ("Nozzle", ["sheet__outlet__code", "nozzle__code", "product__code"]),
    "shift": ("Shift", ["sheet__outlet__code", "sheet__shift_sort_order", "sheet__shift__name"]),
}

TOTALS = {
    "total_delivery": Sum("total_delivery"),
    "testing_litres": Sum("testing_litres"),
    "net_sales_litres": Sum("net_sales_litres"),
    "sales_value": Sum("sales_value"),
}


def summary_lines(*, business, outlets, date_from, date_to, statuses=(DailySalesSheet.Status.APPROVED,), product=None):
    lines = DailySalesLine.objects.for_business(business).filter(
        sheet__outlet__in=outlets,
        sheet__business_date__range=(date_from, date_to),
        sheet__status__in=statuses,
        closing_reading__isnull=False,
    )
    if product is not None:
        lines = lines.filter(product=product)
    return lines


def _label(group_by, row):
    if group_by == "day":
        return row["sheet__business_date"].strftime("%d %b %Y")
    if group_by == "month":
        return row["month"].strftime("%B %Y")
    if group_by == "outlet":
        return f"{row['sheet__outlet__name']} ({row['sheet__outlet__code']})"
    if group_by == "product":
        return row["product__name"]
    if group_by == "nozzle":
        return f"{row['sheet__outlet__code']} · {row['nozzle__code']} ({row['product__code']})"
    return f"{row['sheet__outlet__code']} · {row['sheet__shift__name']}"


def sales_summary(lines, group_by):
    """Return (rows, totals). Each row has a 'label' plus the four figures."""
    if group_by not in GROUPINGS:
        raise ValueError(f"Unknown grouping: {group_by}")
    keys = GROUPINGS[group_by][1]
    grouped = lines.annotate(month=TruncMonth("sheet__business_date")) if group_by == "month" else lines
    rows = list(grouped.values(*keys).annotate(**TOTALS).order_by(*keys))
    for row in rows:
        row["label"] = _label(group_by, row)
    totals = lines.aggregate(**TOTALS)
    return rows, totals
