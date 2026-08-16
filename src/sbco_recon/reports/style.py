"""Shared workbook styling. One place, so every report looks the same."""

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

FONT = "Arial"
CURRENCY = '#,##0.00;(#,##0.00);"-"'
DATE_FMT = "DD-MM-YYYY"

TITLE = Font(name=FONT, size=13, bold=True)
SUBTITLE = Font(name=FONT, size=10, italic=True)
HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
BODY = Font(name=FONT, size=10)
BOLD = Font(name=FONT, size=10, bold=True)
NEGATIVE = Font(name=FONT, size=10, color="C00000")

HEAD_FILL = PatternFill("solid", fgColor="4F7A28")
TOTAL_FILL = PatternFill("solid", fgColor="E8EFE0")

CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center")
RIGHT = Alignment(horizontal="right", vertical="center")

_thin = Side(style="thin", color="9BA89B")
BOX = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def apply_header(cell):
    cell.font = HEAD
    cell.fill = HEAD_FILL
    cell.alignment = CENTER
    cell.border = BOX


def autosize(ws, widths):
    from openpyxl.utils import get_column_letter

    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width


# ── QA-08 / QA-11 ─────────────────────────────────────────────────────
# The engine carries Decimal end to end so an exact match stays exactly
# zero. float() at the worksheet boundary threw that away: an exact 0.05
# was written as 0.0499267578125. Quantise, then hand openpyxl a Decimal,
# which it stores losslessly.
#
# And any user-supplied string that starts like a formula is neutralised,
# because the return leaves the building and opens on someone else's PC.

from decimal import Decimal, ROUND_HALF_UP

CENTS = Decimal("0.01")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def amount(value) -> Decimal:
    """Round to paise and keep it exact."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def write_money(ws, row, col, value):
    cell = ws.cell(row=row, column=col, value=amount(value))
    cell.number_format = CURRENCY
    cell.alignment = RIGHT
    return cell


def safe_text(value) -> str:
    """Stop a spreadsheet treating user text as a live formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in _FORMULA_START else text


def write_text(ws, row, col, value, style=None):
    cell = ws.cell(row=row, column=col, value=safe_text(value))
    cell.font = style or BODY
    return cell
