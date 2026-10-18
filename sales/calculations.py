"""
The Daily Sales formulas. Every screen, correction and report uses this one
function, so the rules can never differ between places.

    Total Nozzle Delivery = Closing Reading - Opening Reading
    Net Customer Sales    = Total Nozzle Delivery - Testing Litres
    Customer Sales Value  = Net Customer Sales x Selling Price per Litre

Testing litres were physically dispensed, so stock reconciliation (Phase 4)
uses the TOTAL nozzle delivery, while sales litres and revenue use NET sales.

Meter rollover or replacement ("meter reset"): the meter jumped from
`reading_before_reset` to `reading_after_reset` during the shift, so

    Total Nozzle Delivery = (Before Reset - Opening) + (Closing - After Reset)

For a rollover, "before" is the meter's maximum (e.g. 1000000.00) and "after"
is 0. For a replacement, "before" is the old meter's last reading and "after"
is the new meter's first reading.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

PAISA = Decimal("0.01")


@dataclass(frozen=True)
class LineFigures:
    total_delivery: Decimal
    testing_litres: Decimal
    net_sales_litres: Decimal
    sales_value: Decimal

    @property
    def stock_consumption(self):
        """Litres that left the tank, including testing litres."""
        return self.total_delivery


def calculate_line(opening, closing, testing, price, *, meter_reset=False, before_reset=None, after_reset=None):
    """
    Validate one nozzle's readings and return its figures.
    Raises ValidationError (keyed by field name) instead of adjusting any value.
    """
    errors = {}
    delivery = None

    if meter_reset:
        if before_reset is None:
            errors["reading_before_reset"] = "Enter the last meter reading before the reset."
        elif before_reset < opening:
            errors["reading_before_reset"] = f"Cannot be less than the opening reading ({opening} L)."
        if after_reset is None:
            errors["reading_after_reset"] = "Enter the first meter reading after the reset."
        elif closing < after_reset:
            errors["closing_reading"] = f"Closing reading cannot be less than the reading after the reset ({after_reset} L)."
        if not errors:
            delivery = (before_reset - opening) + (closing - after_reset)
    elif closing < opening:
        errors["closing_reading"] = (
            f"Closing reading cannot be less than the opening reading ({opening} L). "
            "If the meter rolled over or was replaced, record a meter reset."
        )
    else:
        delivery = closing - opening

    if testing is None or testing < 0:
        errors["testing_litres"] = "Testing litres cannot be negative."
    elif delivery is not None and testing > delivery:
        errors["testing_litres"] = f"Testing litres cannot be more than the total nozzle delivery ({delivery} L)."

    if price is None or price <= 0:
        errors["price_per_litre"] = "A selling price above ₹0 is required."

    if errors:
        raise ValidationError(errors)

    net = delivery - testing
    return LineFigures(
        total_delivery=delivery,
        testing_litres=testing,
        net_sales_litres=net,
        sales_value=(net * price).quantize(PAISA, rounding=ROUND_HALF_UP),
    )
