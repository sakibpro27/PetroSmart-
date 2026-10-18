"""
The reports PetroSmart offers. Each one builds a ReportTable from the same
tenant-scoped queries the rest of the application uses, so an export can only
ever contain the requesting user's own business data.
"""

from decimal import Decimal

from django.db.models import Sum

from finance.models import CreditCustomer
from finance.services import expenses_for
from purchases.services import purchases_for
from sales.models import DailySalesSheet
from sales.reports import GROUPINGS, sales_summary, summary_lines
from sales.services import card_figures
from stock.models import StockLine

from .tables import DATE, LITRES, MONEY, Column, ReportTable

ZERO = Decimal("0")
TESTING_NOTE = ("Testing litres are shown separately and are not counted as customer sales or revenue. "
                "Total nozzle delivery includes testing litres.")


def _period(params):
    return f"{params['date_from']:%d %b %Y} to {params['date_to']:%d %b %Y}"


def sales_summary_report(user, outlets, params):
    group_by = params.get("group_by") or "day"
    lines = summary_lines(business=user.business, outlets=outlets, date_from=params["date_from"],
                          date_to=params["date_to"], product=params.get("product"))
    rows, totals = sales_summary(lines, group_by)
    return ReportTable(
        title=f"Sales summary by {GROUPINGS[group_by][0].lower()}",
        subtitle=_period(params),
        columns=[Column(GROUPINGS[group_by][0]), Column("Total nozzle delivery (L)", LITRES), Column("Testing (L)", LITRES),
                 Column("Net customer sales (L)", LITRES), Column("Customer sales value (₹)", MONEY)],
        rows=[[r["label"], r["total_delivery"], r["testing_litres"], r["net_sales_litres"], r["sales_value"]] for r in rows],
        totals=["Total", totals["total_delivery"], totals["testing_litres"], totals["net_sales_litres"], totals["sales_value"]],
        notes=[TESTING_NOTE],
    )


def nozzle_detail_report(user, outlets, params):
    lines = (summary_lines(business=user.business, outlets=outlets, date_from=params["date_from"],
                           date_to=params["date_to"], product=params.get("product"))
             .select_related("sheet__outlet", "sheet__shift", "nozzle", "product")
             .order_by("sheet__business_date", "sheet__outlet__code", "sheet__shift_sort_order", "nozzle__code"))
    rows = [[l.sheet.business_date, l.sheet.shift.name, l.sheet.outlet.code, l.nozzle.code, l.product.code,
             l.opening_reading, l.closing_reading, l.total_delivery, l.testing_litres, l.net_sales_litres,
             l.price_per_litre, l.sales_value] for l in lines]
    totals = lines.aggregate(d=Sum("total_delivery"), t=Sum("testing_litres"), n=Sum("net_sales_litres"), v=Sum("sales_value"))
    return ReportTable(
        title="Shift cards: nozzle readings",
        subtitle=_period(params),
        columns=[Column("Date", DATE), Column("Shift"), Column("Outlet"), Column("Nozzle"), Column("Product"),
                 Column("Opening (L)", LITRES), Column("Closing (L)", LITRES), Column("Sale Ltr (L)", LITRES),
                 Column("Testing (L)", LITRES), Column("Net sales (L)", LITRES), Column("Rate (₹/L)", MONEY),
                 Column("Sale value (₹)", MONEY)],
        rows=rows,
        totals=["Total", "", "", "", "", "", "", totals["d"], totals["t"], totals["n"], "", totals["v"]],
        notes=[TESTING_NOTE],
    )


def stock_report(user, outlets, params):
    lines = (StockLine.objects.filter(business=user.business, sheet__outlet__in=outlets,
                                      sheet__business_date__range=(params["date_from"], params["date_to"]))
             .select_related("sheet__outlet", "tank", "product")
             .order_by("sheet__business_date", "sheet__outlet__code", "tank__code"))
    rows = [[l.sheet.business_date, l.sheet.outlet.code, l.tank.code, l.product.code,
             l.opening_stock, l.fuel_received, l.total_delivery, l.testing_litres, l.calculated_closing,
             l.measured_closing, l.variation, "Beyond limit" if l.is_flagged else ""] for l in lines]
    totals = lines.aggregate(r=Sum("fuel_received"), d=Sum("total_delivery"), t=Sum("testing_litres"), v=Sum("variation"))
    return ReportTable(
        title="Tank stock reconciliation",
        subtitle=_period(params),
        columns=[Column("Date", DATE), Column("Outlet"), Column("Tank"), Column("Product"),
                 Column("Opening (L)", LITRES), Column("Received (L)", LITRES), Column("Total delivery (L)", LITRES),
                 Column("of which testing (L)", LITRES), Column("Calculated closing (L)", LITRES),
                 Column("Measured closing (L)", LITRES), Column("Variation (L)", LITRES), Column("Flag")],
        rows=rows,
        totals=["Total", "", "", "", "", totals["r"], totals["d"], totals["t"], "", "", totals["v"], ""],
        notes=["Calculated closing = opening + received − total nozzle delivery. Testing litres are part of the "
               "total delivery and are not subtracted again.",
               "Variation = measured − calculated. Observed litres, no temperature correction."],
    )


def purchases_report(user, outlets, params):
    purchases = (purchases_for(user).filter(outlet__in=outlets,
                                            delivery_date__range=(params["date_from"], params["date_to"]))
                 .select_related("outlet", "supplier", "product").annotate(received=Sum("receipts__litres"))
                 .order_by("delivery_date", "pk"))
    if params.get("product"):
        purchases = purchases.filter(product=params["product"])
    rows, invoiced, received, amount = [], ZERO, ZERO, ZERO
    for p in purchases:
        got = p.received or ZERO
        rows.append([p.delivery_date, p.invoice_number, p.supplier.name, p.outlet.code, p.product.code,
                     p.invoiced_litres, got, got - p.invoiced_litres, p.purchase_rate, p.invoice_amount])
        invoiced, received, amount = invoiced + p.invoiced_litres, received + got, amount + p.invoice_amount
    return ReportTable(
        title="Fuel purchases and deliveries",
        subtitle=_period(params),
        columns=[Column("Delivered", DATE), Column("Invoice"), Column("Supplier"), Column("Outlet"), Column("Product"),
                 Column("Invoiced (L)", LITRES), Column("Received (L)", LITRES), Column("Difference (L)", LITRES),
                 Column("Rate (₹/L)", MONEY), Column("Invoice amount (₹)", MONEY)],
        rows=rows,
        totals=["Total", "", "", "", "", invoiced, received, received - invoiced, "", amount],
        notes=["Difference = litres received into the tanks − invoiced quantity. Invoice amounts are as printed; "
               "PetroSmart does not calculate taxes."],
    )


CASH_KEYS = ("total_fuel", "lube", "customer_receipts", "credit", "general_credit", "bank_card", "company_card",
             "phone_wallet", "expenses", "cash_collection", "balance")


def shift_cash_report(user, outlets, params):
    cards = (DailySalesSheet.objects.filter(business=user.business, outlet__in=outlets,
                                            business_date__range=(params["date_from"], params["date_to"]))
             .select_related("outlet", "shift", "dispenser", "employee")
             .order_by("business_date", "outlet__code", "shift_sort_order", "pk"))
    rows, sums = [], {key: ZERO for key in CASH_KEYS}
    for card in cards:
        f = card_figures(card)
        rows.append([card.business_date, card.shift.name, card.outlet.code,
                     card.dispenser.code if card.dispenser else "", str(card.employee or ""),
                     *[f[key] for key in CASH_KEYS]])
        for key in CASH_KEYS:
            sums[key] += f[key]
    return ReportTable(
        title="Shift card cash summary",
        subtitle=_period(params),
        columns=[Column("Date", DATE), Column("Shift"), Column("Outlet"), Column("MPD / DU"), Column("Employee"),
                 Column("Total fuel (₹)", MONEY), Column("Lube (₹)", MONEY), Column("Cust. receipt (₹)", MONEY),
                 Column("Credit (₹)", MONEY), Column("Gen. credit (₹)", MONEY), Column("Bank card (₹)", MONEY),
                 Column("Company card (₹)", MONEY), Column("Phone wallet (₹)", MONEY), Column("Exp by DSM (₹)", MONEY),
                 Column("Cash collected (₹)", MONEY), Column("Balance / short (₹)", MONEY)],
        rows=rows,
        totals=["Total", "", "", "", "", *[sums[key] for key in CASH_KEYS]],
        notes=["Balance = cash collected − (total fuel + lube + customer receipts − credit − gen. credit − bank card "
               "− company card − phone wallet − expenses by DSM). A negative balance is a shortage."],
    )


def expenses_report(user, outlets, params):
    expenses = (expenses_for(user).filter(outlet__in=outlets,
                                          expense_date__range=(params["date_from"], params["date_to"]))
                .select_related("outlet", "category", "method").order_by("expense_date", "pk"))
    rows = [[e.expense_date, e.outlet.code, e.category.name, e.description, e.method.name, e.paid_to, e.amount]
            for e in expenses]
    return ReportTable(
        title="Expenses",
        subtitle=_period(params),
        columns=[Column("Date", DATE), Column("Outlet"), Column("Category"), Column("Description"), Column("Paid by"),
                 Column("Paid to"), Column("Amount (₹)", MONEY)],
        rows=rows,
        totals=["Total", "", "", "", "", "", expenses.aggregate(total=Sum("amount"))["total"] or ZERO],
    )


def credit_report(user, outlets, params):
    customers = CreditCustomer.objects.for_business(user.business).order_by("name")
    rows, total = [], ZERO
    for customer in customers:
        balance = customer.balance()
        over = customer.credit_limit is not None and balance > customer.credit_limit
        rows.append([customer.name, customer.phone, customer.credit_limit, balance, "Over limit" if over else ""])
        total += balance
    return ReportTable(
        title="Credit outstanding",
        subtitle="Balances as of today",
        columns=[Column("Customer"), Column("Phone"), Column("Credit limit (₹)", MONEY), Column("Balance owed (₹)", MONEY),
                 Column("Flag")],
        rows=rows,
        totals=["Total", "", "", total, ""],
        notes=["Balance = opening balance + credit sales − payments ± Dealer adjustments."],
    )


REPORTS = {
    "sales-summary": {"title": "Sales summary", "build": sales_summary_report, "dealer_only": False,
                      "options": ("group_by", "product"),
                      "description": "Delivery, testing, net sales and value by day, month, outlet, product, nozzle or shift."},
    "nozzle-readings": {"title": "Shift card nozzle readings", "build": nozzle_detail_report, "dealer_only": False,
                        "options": ("product",),
                        "description": "Every nozzle line with opening, closing, testing and value."},
    "tank-stock": {"title": "Tank stock reconciliation", "build": stock_report, "dealer_only": False, "options": (),
                   "description": "Opening, received, delivery, calculated and measured stock with variations."},
    "purchases": {"title": "Fuel purchases", "build": purchases_report, "dealer_only": False, "options": ("product",),
                  "description": "Invoices with invoiced and received quantities."},
    "shift-cash": {"title": "Shift card cash summary", "build": shift_cash_report, "dealer_only": False, "options": (),
                   "description": "Each card's fuel, lube, receipts, credit, cards, wallet, expenses, cash and short."},
    "expenses": {"title": "Expenses", "build": expenses_report, "dealer_only": False, "options": (),
                 "description": "Expenses by date, outlet and category."},
    "credit-outstanding": {"title": "Credit outstanding", "build": credit_report, "dealer_only": True, "options": (),
                           "no_period": True, "description": "What each credit customer owes now."},
}
