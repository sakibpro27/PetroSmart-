"""
A report is built once as a plain table (ReportTable) and then shown on
screen, or exported to Excel or PDF. All three use the same rows, so an
export can never show different figures from the screen.
"""

from dataclasses import dataclass, field

TEXT, DATE, LITRES, MONEY, NUMBER = "text", "date", "litres", "money", "number"


@dataclass
class Column:
    label: str
    kind: str = TEXT

    @property
    def numeric(self):
        return self.kind in (LITRES, MONEY, NUMBER)


@dataclass
class ReportTable:
    title: str
    subtitle: str
    columns: list
    rows: list = field(default_factory=list)
    totals: list | None = None
    notes: list = field(default_factory=list)
