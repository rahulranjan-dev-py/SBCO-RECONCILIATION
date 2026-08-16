"""Locale-independent coercion of dates, amounts and account codes.

The legacy tool required every user to set Windows to English (India) because
it relied on VBA's CDate/IsDate, which follow the machine locale. These
functions never consult the locale, so the same file parses identically on
every machine.
"""

from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

# Excel's day-zero. Excel wrongly treats 1900 as a leap year, so serials
# below 61 are ambiguous; we reject them rather than guess.
_EXCEL_EPOCH = _dt.date(1899, 12, 30)
_MIN_SERIAL = 61
_MAX_SERIAL = 80000  # ~year 2119

# Day-first formats only. Indian government reports are uniformly dd-mm-yyyy;
# accepting mm-dd-yyyy as a fallback would silently swap 03/04 and 04/03.
_DATE_FORMATS = (
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%d-%m-%y", "%d/%m/%y",
    "%Y-%m-%d", "%Y/%m/%d",
    "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y",
    "%b-%y", "%b-%Y", "%B-%Y",
)

_MONTH_ONLY = {"%b-%y", "%b-%Y", "%B-%Y"}


def parse_date(value, *, allow_month_only: bool = False) -> Optional[_dt.date]:
    """Coerce a cell value to a date, or return None.

    Handles datetime objects, Excel serial numbers and the string formats
    used by Finacle and APT exports. Never guesses month-first ordering.
    """
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float, Decimal)):
        serial = float(value)
        if not (_MIN_SERIAL <= serial <= _MAX_SERIAL):
            return None
        return _EXCEL_EPOCH + _dt.timedelta(days=int(serial))

    text = str(value).strip()
    if not text:
        return None

    # A bare number arriving as text is still an Excel serial.
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return parse_date(float(text))

    text = re.sub(r"\s+", " ", text)
    for fmt in _DATE_FORMATS:
        if fmt in _MONTH_ONLY and not allow_month_only:
            continue
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value) -> Optional[Decimal]:
    """Coerce a cell value to Decimal. Returns None if not a number.

    Decimal, not float: these are rupee figures that get summed thousands of
    times and compared against zero. Binary floating point turns an exact
    match into a 0.0000001 difference and puts a phantom row on a PAO return.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))

    text = str(value).strip()
    if not text or text in {"-", "--", "NA", "N/A", "nil", "Nil", "NIL"}:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-"):  # trailing-minus convention
        negative, text = True, text[:-1]

    text = text.replace("\u20b9", "").replace("Rs.", "").replace("Rs", "")
    text = text.replace(",", "").replace(" ", "").replace("\xa0", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def parse_account_code(value) -> Optional[str]:
    """Normalise an account code to its canonical digit string.

    Excel returns these as floats (8001000100.0), which is why the legacy
    dashboard displays them that way.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value != int(value):
            return None
        value = int(value)
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    text = re.sub(r"[^\d]", "", text)
    if not text or len(text) < 8:
        return None
    return text


def clean_text(value) -> str:
    """Collapse whitespace and repair the mojibake found in the source data."""
    if value is None:
        return ""
    text = str(value)
    for bad, good in (("\u00e2\u20ac\u201c", "-"), ("\u00e2\u20ac\u2122", "'"),
                      ("\u00e2\u20ac\u0153", '"'), ("\u00e2\u20ac", "-")):
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()
