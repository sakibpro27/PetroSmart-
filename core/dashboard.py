"""
Figures for the dashboard, from the saved Shift Cards. Every query is limited
to the business and to the outlets the user may see.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum

from finance.models import Expense
from finance.services import outstanding_total
from purchases.models import FuelPurchase
from sales.models import DailySalesLine, DailySalesSheet
from sales.services import card_figures
from station.models import FuelProduct
from stock.models import StockLine
from stock.services import book_stock_for

ZERO = Decimal("0")
CHART_DAYS = 14


def _sum(qs, field):
    return qs.aggregate(total=Sum(field))["total"] or ZERO


def sales_by_category(business, outlets, day):
    lines = DailySalesLine.objects.filter(business=business, sheet__outlet__in=outlets, sheet__business_date=day,
                                          closing_reading__isnull=False)
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
                                      sheet__business_date__range=(start, day), closing_reading__isnull=False)
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
    """Each active tank's book stock now: last dip + received - sold on shift cards since."""
    return book_stock_for(outlets.filter(business=business))


def money(cards):
    """How the day's money was received, across its Shift Cards."""
    totals = {key: ZERO for key in ("cash_collection", "phone_wallet", "bank_card", "company_card", "credit",
                                    "general_credit", "expenses", "balance")}
    for card in cards:
        figures = card_figures(card)
        for key in totals:
            totals[key] += figures[key]
    rows = [("Cash", totals["cash_collection"]), ("Phone wallet (UPI)", totals["phone_wallet"]),
            ("Bank card", totals["bank_card"]), ("Company card", totals["company_card"]),
            ("Credit sales", totals["credit"] + totals["general_credit"])]
    return {"rows": rows, "expenses": totals["expenses"], "balance": totals["balance"],
            "chart": {"labels": [label for label, _ in rows], "values": [float(amount) for _, amount in rows]}}


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
    short_cards = []
    for card in (DailySalesSheet.objects.filter(business=business, outlet__in=outlets,
                                                business_date__range=(day - timedelta(days=7), day))
                 .select_related("outlet", "shift", "employee").order_by("-business_date")):
        balance = card_figures(card)["balance"]
        if balance < 0:
            short_cards.append({"card": card, "balance": balance})
    return {"flagged_stock": flagged, "meter_resets": list(resets), "short_cards": short_cards[:8]}


def build(user, outlets, day):
    business = user.business
    sales, totals = sales_by_category(business, outlets, day)
    month_start = day.replace(day=1)
    cards = DailySalesSheet.objects.filter(business=business, outlet__in=outlets, business_date=day)
    return {
        "day": day,
        "sales": sales,
        "totals": totals,
        "card_count": cards.count(),
        "chart": daily_chart(business, outlets, day),
        "tanks": tank_stock(business, outlets),
        "deliveries": FuelPurchase.objects.filter(business=business, outlet__in=outlets)
        .select_related("supplier", "product", "outlet").order_by("-delivery_date", "-pk")[:5],
        "payments": money(cards),
        "month_expenses": _sum(Expense.objects.filter(business=business, outlet__in=outlets,
                                                      expense_date__range=(month_start, day)), "amount"),
        "outstanding": outstanding_total(business) if user.is_dealer else None,
        "exceptions": exceptions(business, outlets, day),
    }
