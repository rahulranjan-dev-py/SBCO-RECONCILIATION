"""Turn detected rows into typed Entry records."""

from __future__ import annotations

from pathlib import Path

from ..errors import FileRejected
from ..model import Entry, Office, Source
from ..normalize import clean_text, parse_account_code, parse_amount, parse_date
from .detect import Detection, ReportKind

# A file where most rows fail to parse is the wrong file, not a bad file.
MIN_PARSE_RATE = 0.50


def _cell(row, idx):
    return row[idx] if idx is not None and idx < len(row) else None


def parse_entries(rows, detection: Detection, path="") -> tuple:
    """Return (entries, warnings).

    Rows that cannot be parsed are counted and reported rather than skipped
    in silence. If too many fail, the file is rejected outright.
    """
    if not detection.ok:
        raise FileRejected(path, "unrecognised report", detection.reason)

    if detection.form is not None:
        from .glwise_form import parse_form

        return parse_form(rows, detection.form, path)

    cols = detection.columns
    source = detection.source
    entries, warnings = [], []
    skipped_no_date = skipped_no_code = skipped_no_amount = 0
    considered = 0

    for row in rows[detection.header_row + 1:]:
        if not row or not any(clean_text(c) for c in row):
            continue

        # Skip the total/footer rows these reports append.
        first = clean_text(_cell(row, 0)).lower()
        if first.startswith(("total", "grand total", "sub total", "progressive")):
            continue

        considered += 1
        txn_date = parse_date(_cell(row, cols.get("txn_date")))
        code = parse_account_code(_cell(row, cols.get("account_code")))
        amount = parse_amount(_cell(row, cols.get("amount")))

        if txn_date is None:
            skipped_no_date += 1
            continue
        if code is None:
            skipped_no_code += 1
            continue
        if amount is None:
            skipped_no_amount += 1
            continue

        entries.append(Entry(
            txn_date=txn_date,
            account_code=code,
            amount=amount,
            source=source,
            office_id=clean_text(_cell(row, cols.get("office_id"))),
            sol_id=clean_text(_cell(row, cols.get("sol_id"))),
            description=clean_text(_cell(row, cols.get("description"))),
        ))

    if considered and len(entries) / considered < MIN_PARSE_RATE:
        raise FileRejected(
            path, "too many unreadable rows",
            f"{len(entries)} of {considered} rows parsed; "
            f"{skipped_no_date} bad dates, {skipped_no_code} bad account codes, "
            f"{skipped_no_amount} bad amounts",
        )
    if not entries:
        raise FileRejected(path, "no data rows found",
                           f"header located at row {detection.header_row + 1}")

    for label, count in (("unreadable date", skipped_no_date),
                         ("unreadable account code", skipped_no_code),
                         ("unreadable amount", skipped_no_amount)):
        if count:
            warnings.append(f"{Path(path).name}: skipped {count} row(s) with {label}")

    return entries, warnings


def parse_offices(rows, detection: Detection, path="") -> list:
    """Read an office master file into Office records, validating as we go."""
    if detection.kind is not ReportKind.OFFICE_MASTER:
        raise FileRejected(path, "not an office master file", detection.reason)

    cols = detection.columns
    offices, seen_ids, problems = [], set(), []

    for n, row in enumerate(rows[detection.header_row + 1:], start=detection.header_row + 2):
        name = clean_text(_cell(row, cols.get("office_name")))
        office_id = clean_text(_cell(row, cols.get("office_id"))).removesuffix(".0")
        sol_id = clean_text(_cell(row, cols.get("sol_id"))).removesuffix(".0")
        sol_group = clean_text(_cell(row, cols.get("sol_group"))).removesuffix(".0")

        if not any((name, office_id, sol_id)):
            continue
        missing = [lbl for lbl, val in (("office name", name), ("office ID", office_id),
                                        ("SOL ID/BO code", sol_id),
                                        ("SOL ID group", sol_group)) if not val]
        if missing:
            problems.append(f"row {n}: missing {', '.join(missing)}")
            continue
        if office_id in seen_ids:
            problems.append(f"row {n}: duplicate office ID {office_id}")
            continue
        seen_ids.add(office_id)
        offices.append(Office(name=name, office_id=office_id,
                              sol_id=sol_id, sol_group=sol_group))

    if not offices:
        raise FileRejected(path, "office master contained no valid rows",
                           "; ".join(problems[:5]))

    # Every BO's SOL group must point at a real SO/HO SOL ID.
    known_sols = {o.sol_id for o in offices}
    for office in offices:
        if office.sol_group not in known_sols:
            problems.append(
                f"{office.name}: SOL ID group {office.sol_group} does not match "
                f"any office in this file")

    if problems:
        raise FileRejected(path, "office master has errors", "; ".join(problems[:5]))
    return offices
