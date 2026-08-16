"""Indian financial-year arithmetic.

Replaces the legacy VALIDATOR sheet, a hardcoded 16-row lookup table that
stopped at 31-Mar-2029. These functions work for any date.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date


def fy_start_year(d: date) -> int:
    """Return the calendar year in which d's financial year began (Apr-Mar)."""
    return d.year if d.month >= 4 else d.year - 1


def fy_label(d: date) -> str:
    """'2026/27' for any date in FY 2026-27."""
    s = fy_start_year(d)
    return f"{s}/{(s + 1) % 100:02d}"


def quarter(d: date) -> int:
    """Financial-year quarter 1-4. Q1 = Apr-Jun."""
    return ((d.month + 8) % 12) // 3 + 1


def quarter_label(d: date) -> str:
    """'Q2 - 2026/27' - same format the legacy VALIDATOR sheet produced."""
    return f"Q{quarter(d)} - {fy_label(d)}"


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def month_start(d: date) -> date:
    return d.replace(day=1)


MAX_PERIOD_DAYS = 400   # a financial year plus slack; anything more is a typo


@dataclass(frozen=True)
class Period:
    """An inclusive date range."""

    start: date
    end: date

    def __post_init__(self):
        if self.start > self.end:
            raise ValueError(
                f"The start date ({self.start:%d-%m-%Y}) is after the end date "
                f"({self.end:%d-%m-%Y}).")
        span = (self.end - self.start).days + 1
        if span > MAX_PERIOD_DAYS:
            # QA-13: an unbounded range meant tens of thousands of rows and a
            # coverage scan over every calendar day in between.
            raise ValueError(
                f"That period covers {span:,} days. Reconcile at most "
                f"{MAX_PERIOD_DAYS} days at a time - check the years you typed.")

    @classmethod
    def for_month(cls, d: date) -> "Period":
        return cls(month_start(d), month_end(d))

    @classmethod
    def for_quarter(cls, d: date) -> "Period":
        q_first_month = (quarter(d) - 1) * 3 + 4
        year = fy_start_year(d) + (0 if q_first_month <= 12 else 1)
        m = q_first_month if q_first_month <= 12 else q_first_month - 12
        start = date(year, m, 1)
        end_m = m + 2
        end_y = year + (1 if end_m > 12 else 0)
        end_m = end_m - 12 if end_m > 12 else end_m
        return cls(start, month_end(date(end_y, end_m, 1)))

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def days(self):
        from datetime import timedelta

        d = self.start
        while d <= self.end:
            yield d
            d += timedelta(days=1)

    def __str__(self):
        return f"{self.start:%d-%m-%Y} to {self.end:%d-%m-%Y}"
