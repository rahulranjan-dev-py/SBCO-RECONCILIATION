"""Read any supported spreadsheet into a plain list of rows.

Deliberately format-agnostic: the rest of the engine never learns whether the
data arrived as .xls, .xlsx or .csv.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..errors import FileRejected

MAX_SCAN_ROWS = 200_000


def read_rows(path, max_rows: int = MAX_SCAN_ROWS) -> list:
    """Return a list of row-lists. Values keep their native types."""
    p = Path(path)
    if not p.exists():
        raise FileRejected(p, "file not found")
    if p.stat().st_size == 0:
        raise FileRejected(p, "file is empty")

    suffix = p.suffix.lower()
    try:
        if suffix in (".xlsx", ".xlsm"):
            return _read_openpyxl(p, max_rows)
        if suffix == ".xlsb":
            return _read_xlsb(p, max_rows)
        if suffix == ".xls":
            return _read_legacy_xls(p, max_rows)
        if suffix in (".csv", ".txt", ".tsv"):
            return _read_csv(p, max_rows)
    except FileRejected:
        raise
    except Exception as exc:
        raise FileRejected(p, "could not be opened", str(exc)) from exc
    raise FileRejected(p, "unsupported file type", suffix or "no extension")


def _read_openpyxl(p, max_rows):
    """Read an OOXML workbook.

    Handed the raw bytes rather than the path, because openpyxl decides what a
    file is from its *extension* and refuses anything ending .xls outright.
    Portals routinely emit a real .xlsx named REPORT.xls, and by path those
    were rejected with an error about the old format even though the content
    was perfectly readable.
    """
    from io import BytesIO

    from openpyxl import load_workbook

    source = BytesIO(Path(p).read_bytes()) if Path(p).suffix.lower() != ".xlsx" else p
    wb = load_workbook(source, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        out = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                break
            out.append(list(row))
        return out
    finally:
        wb.close()


def _read_xlsb(p, max_rows):
    from pyxlsb import open_workbook

    with open_workbook(str(p)) as wb:
        with wb.get_sheet(wb.sheets[0]) as sheet:
            out = []
            for i, row in enumerate(sheet.rows()):
                if i >= max_rows:
                    break
                out.append([c.v for c in row])
            return out


def _read_legacy_xls(p, max_rows):
    """Legacy BIFF .xls - what APT 2.0 and Finacle MIS actually emit.

    Many 'xls' downloads from web portals are really HTML or CSV wearing an
    .xls extension, so sniff the magic bytes before choosing a reader.
    """
    head = p.open("rb").read(2048)
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        try:
            import xlrd
        except ImportError as exc:
            raise FileRejected(
                p, "legacy .xls support not installed",
                "pip install xlrd, or re-save the file as .xlsx",
            ) from exc
        book = xlrd.open_workbook(str(p))
        sheet = book.sheet_by_index(0)
        return [sheet.row_values(r) for r in range(min(sheet.nrows, max_rows))]

    lowered = head[:512].lower()
    if b"<html" in lowered or b"<table" in lowered:
        return _read_html_table(p, max_rows)
    if head[:2] == b"PK":
        return _read_openpyxl(p, max_rows)
    return _read_csv(p, max_rows)


def _read_html_table(p, max_rows):
    """Portal 'Excel' exports are frequently an HTML table."""
    import html.parser

    class TableParser(html.parser.HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.rows, self.row, self.cell, self.in_cell = [], [], [], False

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th"):
                self.in_cell, self.cell = True, []

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.in_cell:
                self.row.append("".join(self.cell).strip())
                self.in_cell = False
            elif tag == "tr" and self.row:
                self.rows.append(self.row)

        def handle_data(self, data):
            if self.in_cell:
                self.cell.append(data)

    parser = TableParser()
    parser.feed(p.read_text(encoding="utf-8", errors="replace"))
    return parser.rows[:max_rows]


def _read_csv(p, max_rows):
    sample = p.open("r", encoding="utf-8", errors="replace").read(8192)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    with p.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        return [row for i, row in enumerate(csv.reader(fh, dialect)) if i < max_rows]
