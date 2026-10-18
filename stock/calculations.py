"""
Tank stock reconciliation formula.

    Calculated Closing Stock = Opening Stock + Fuel Received - Total Nozzle Delivery
    Stock Variation          = Measured (dip) Closing Stock - Calculated Closing Stock

Total Nozzle Delivery already INCLUDES testing litres, because that fuel
physically left the tank. Testing litres are therefore shown as a component
of the delivery and are deliberately NOT a parameter here, so they can never
be subtracted a second time.

A negative variation means less fuel in the tank than the records explain
(possible loss or leakage); a positive one means more.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class StockFigures:
    calculated_closing: Decimal
    variation: Decimal | None


def reconcile(opening_stock, fuel_received, total_delivery, measured_closing=None):
    calculated = opening_stock + fuel_received - total_delivery
    variation = None if measured_closing is None else measured_closing - calculated
    return StockFigures(calculated_closing=calculated, variation=variation)
