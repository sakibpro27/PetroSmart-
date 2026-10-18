"""
Indian number formatting for templates.

    {% load ps_format %}
    {{ value|inr }}     ->  ₹1,23,456.78
    {{ litres|qty }}    ->  1,23,456.78   (column headings say "L")
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template

register = template.Library()


def indian_grouping(value, places=2):
    """Format a number with Indian digit grouping: 12,34,56,789.00."""
    try:
        number = Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return ""
    sign = "-" if number < 0 else ""
    whole, _, fraction = f"{abs(number):.{places}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join([head, *pairs, tail]) if head else ",".join([*pairs, tail])
    return f"{sign}{whole}.{fraction}" if places else f"{sign}{whole}"


@register.filter
def inr(value):
    if value is None or value == "":
        return "—"
    formatted = indian_grouping(value)
    if formatted.startswith("-"):
        return f"−₹{formatted[1:]}"
    return f"₹{formatted}"


@register.filter
def report_cell(value, column):
    """Format a report cell according to its column kind (see reports.tables)."""
    if value is None or value == "":
        return "—" if column.numeric else ""
    if column.kind == "money":
        return inr(value)
    if column.numeric:
        return indian_grouping(value)
    if column.kind == "date" and hasattr(value, "strftime"):
        return value.strftime("%d %b %Y")
    return value  # includes the "Total" label in a totals row


@register.filter
def qty(value):
    if value is None or value == "":
        return "—"
    return indian_grouping(value)
