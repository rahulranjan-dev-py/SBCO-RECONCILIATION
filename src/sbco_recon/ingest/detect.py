"""Identify which report an uploaded file is, by matching its header row.

The legacy tool decided this with one comparison:

    If ws.Range("L2").value = "Progressive Total" Then

A file passed if one cell in one fixed position held one string. It therefore
accepted a cashbook for the wrong month, a truncated download or any workbook
that happened to have that text in L2, and rejected a valid cashbook whose
columns had shifted by one - which is what happens whenever the source system
adds a column.

Here, detection is header-driven: we locate the header row anywhere in the
first 40 rows, map logical fields to whatever column they actually occupy, and
require a minimum score before accepting. Adding a column upstream no longer
breaks anything, and every rejection names its reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..model import Source
from ..normalize import (clean_text, parse_account_code, parse_amount,
                         parse_date)

HEADER_SEARCH_ROWS = 40
MIN_FIELD_SCORE = 0.40
VALIDATION_SAMPLE = 25
MIN_VALID_RATE = 0.60


class ReportKind(str, Enum):
    CASHBOOK = "cashbook"
    FINACLE_GL_WISE = "finacle_gl_wise"
    FINACLE_TXN = "finacle_txn"
    APT_ACCOUNTING_DETAILS = "apt_accounting_details"
    OFFICE_MASTER = "office_master"
    UNKNOWN = "unknown"


SOURCE_FOR_KIND = {
    ReportKind.CASHBOOK: Source.CASHBOOK,
    ReportKind.FINACLE_GL_WISE: Source.FINACLE_GL,
    ReportKind.FINACLE_TXN: Source.FINACLE_TXN,
    ReportKind.APT_ACCOUNTING_DETAILS: Source.APT_DETAILS,
}


# Words that mean "this is a derived or running figure", never a single
# transaction amount. A column containing any of them cannot be bound to
# `amount` (QA-01).
RUNNING_TOTAL_WORDS = ("progressive", "grand", "running", "cumulative",
                       "balance", "opening", "closing", "brought", "carried",
                       "todate", "ytd")

VALIDATORS = {
    "date": parse_date,
    "code": parse_account_code,
    "amount": parse_amount,
}


def _norm(text) -> str:
    """Fold a header cell for comparison: lowercase, alphanumerics only."""
    return "".join(ch for ch in clean_text(text).lower() if ch.isalnum())


@dataclass
class FieldSpec:
    """One logical column, the header spellings that identify it, and the
    words that disqualify a column from being it."""

    name: str
    aliases: tuple
    required: bool = True
    deny: tuple = ()
    checks: str = ""          # key into VALIDATORS, or "" for free text

    def score(self, header) -> float:
        """0.0 (no match) to 1.0 (exact). A partial match can never beat an
        exact one, which is what stops "Total" and "Progressive Total" being
        treated as interchangeable."""
        h = _norm(header)
        if not h:
            return 0.0
        if any(_norm(word) in h for word in self.deny):
            return 0.0

        best = 0.0
        for alias in self.aliases:
            a = _norm(alias)
            if not a:
                continue
            if h == a:
                return 1.0
            if len(a) >= 4 and a in h:
                best = max(best, 0.50 + 0.24 * (len(a) / len(h)))
            elif len(h) >= 4 and h in a:
                best = max(best, 0.45)
        return best


@dataclass
class Schema:
    kind: ReportKind
    fields: tuple
    # Header text that must appear somewhere in the row for a confident match.
    signature: tuple = ()
    min_score: float = 0.75

    @property
    def required_fields(self):
        return [f for f in self.fields if f.required]


# Column layouts recovered from the legacy staging sheets, which were direct
# pastes of the source files. Aliases cover the spelling variants observed
# (including the "DESCRIPRTION" typo carried in TEMP.FIN.GL and TEMP.FIN.TR).

SCHEMAS = (
    Schema(
        kind=ReportKind.CASHBOOK,
        signature=("progressive total",),
        fields=(
            FieldSpec("txn_date", ("date", "txn date", "transaction date"),
                      checks="date"),
            FieldSpec("office_name", ("office name", "office"), required=False),
            FieldSpec("office_id", ("office id", "officeid"), required=False),
            FieldSpec("account_code",
                      ("account code", "acct code", "a/c code", "ac code", "gl code"),
                      deny=("description", "desc", "name"), checks="code"),
            FieldSpec("description", ("account code description", "description", "desc"),
                      required=False),
            FieldSpec("part", ("part",), required=False),
            FieldSpec("side", ("receipts/payments", "receipt or payment", "type"),
                      required=False),
            FieldSpec("amount", ("total", "amount", "amt", "net amount"),
                      deny=RUNNING_TOTAL_WORDS, checks="amount"),
            FieldSpec("progressive_total", ("progressive total",), required=False),
        ),
    ),
    Schema(
        kind=ReportKind.FINACLE_GL_WISE,
        signature=("sol id",),
        fields=(
            FieldSpec("txn_date", ("date", "tran date", "transaction date", "post date"),
                      checks="date"),
            FieldSpec("sol_id", ("sol id", "solid", "sol")),
            FieldSpec("office_name", ("office", "office name", "sol desc"), required=False),
            FieldSpec("account_code", ("account code", "acct code", "gl code",
                                       "a/c code", "ac code"),
                      deny=("description", "desc", "name"), checks="code"),
            FieldSpec("description", ("descriprtion", "description", "gl description",
                                      "acct description"), required=False),
            FieldSpec("amount", ("receipt", "amount", "amt", "net amount"),
                      deny=RUNNING_TOTAL_WORDS, checks="amount"),
        ),
    ),
    Schema(
        kind=ReportKind.FINACLE_TXN,
        fields=(
            FieldSpec("txn_date", ("date", "tran date", "transaction date"),
                      checks="date"),
            FieldSpec("sol_id", ("sol id", "solid", "sol")),
            FieldSpec("account_code", ("account code", "acct code", "gl code", "ac code"),
                      deny=("description", "desc", "name"), checks="code"),
            FieldSpec("description", ("descriprtion", "description"), required=False),
            FieldSpec("amount", ("amt", "amount", "net amount"),
                      deny=RUNNING_TOTAL_WORDS, checks="amount"),
        ),
    ),
    Schema(
        kind=ReportKind.APT_ACCOUNTING_DETAILS,
        fields=(
            FieldSpec("txn_date", ("date", "deduct date", "transaction date"),
                      checks="date"),
            FieldSpec("office_id", ("office id", "officeid")),
            FieldSpec("office_name", ("office name", "office"), required=False),
            FieldSpec("account_code", ("acct code", "account code", "a/c code", "ac code"),
                      deny=("description", "desc", "name"), checks="code"),
            FieldSpec("amount", ("amt", "amount", "total"),
                      deny=RUNNING_TOTAL_WORDS, checks="amount"),
            FieldSpec("remarks", ("remarks", "narration"), required=False),
        ),
    ),
    Schema(
        kind=ReportKind.OFFICE_MASTER,
        signature=("sol_id_group", "sol id group"),
        fields=(
            FieldSpec("office_name", ("office_name", "office name")),
            FieldSpec("office_id", ("office_id", "office id")),
            FieldSpec("sol_id", ("sol_id/bo_code", "sol id", "sol_id", "bo code"),
                      deny=("group",)),
            FieldSpec("sol_group", ("sol_id_group", "sol id group", "sol group")),
        ),
    ),
)


@dataclass
class Detection:
    """What we concluded about a file."""

    kind: ReportKind
    header_row: int = -1
    columns: dict = field(default_factory=dict)   # logical name -> column index
    score: float = 0.0
    reason: str = ""
    # Set when the file is a form-style report (date/SOL in a header block, not
    # in columns); parsing is then delegated to the matching form parser.
    form: object = None

    @property
    def ok(self) -> bool:
        return self.kind is not ReportKind.UNKNOWN

    @property
    def source(self) -> Optional[Source]:
        return SOURCE_FOR_KIND.get(self.kind)


def _assign(row, schema) -> tuple:
    """Bind fields to columns by best score across the whole row.

    Every (field, column) pair is scored, then pairs are taken highest-first so
    the strongest claim on a column wins. Binding by first substring hit is
    what let a running total be read as a transaction amount (QA-01).
    """
    pairs = []
    for spec in schema.fields:
        for idx, cell in enumerate(row):
            s = spec.score(cell)
            if s >= MIN_FIELD_SCORE:
                pairs.append((s, spec.name, idx))

    pairs.sort(key=lambda p: (-p[0], p[2]))   # ties break leftmost, for stability

    columns, used_fields, used_cols = {}, set(), set()
    for _s, name, idx in pairs:
        if name in used_fields or idx in used_cols:
            continue
        columns[name] = idx
        used_fields.add(name)
        used_cols.add(idx)

    required = schema.required_fields
    if not required:
        return 0.0, {}
    score = sum(1 for spec in required if spec.name in columns) / len(required)

    if schema.signature:
        joined = " | ".join(_norm(c) for c in row)
        if not any(_norm(sig) in joined for sig in schema.signature):
            score *= 0.6
    return score, columns


def _verify_content(rows, header_row, schema, columns) -> tuple:
    """Check each bound column against the data beneath it.

    A header can be worded convincingly and still sit above the wrong data.
    Sampling the rows turns a plausible mapping into a verified one (QA-02).
    """
    sample = [r for r in rows[header_row + 1: header_row + 1 + VALIDATION_SAMPLE * 3]
              if r and any(clean_text(c) for c in r)][:VALIDATION_SAMPLE]
    if not sample:
        return True, ""

    for spec in schema.fields:
        if not spec.checks or spec.name not in columns:
            continue
        idx = columns[spec.name]
        parse = VALIDATORS[spec.checks]
        seen = ok = 0
        for row in sample:
            if idx >= len(row):
                continue
            raw = row[idx]
            if raw is None or clean_text(raw) == "":
                continue
            seen += 1
            if parse(raw) is not None:
                ok += 1
        if seen and ok / seen < MIN_VALID_RATE:
            head = rows[header_row]
            label = clean_text(head[idx]) if idx < len(head) else "?"
            return False, (f"the column headed '{label}' does not hold "
                           f"{spec.checks} values ({ok} of {seen} rows could be read)")
    return True, ""


def detect_kind(rows) -> Detection:
    """Identify the report and locate its columns.

    Scans the first 40 rows because portal exports carry title and filter
    banners above the real header.
    """
    if not rows:
        return Detection(ReportKind.UNKNOWN, reason="file contains no rows")

    best = Detection(ReportKind.UNKNOWN, reason="no recognisable header row found")
    best_score = 0.0

    for row_idx, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        if not row or sum(1 for c in row if clean_text(c)) < 3:
            continue
        for schema in SCHEMAS:
            score, columns = _assign(row, schema)
            if score <= best_score:
                continue

            if score >= schema.min_score:
                verified, why = _verify_content(rows, row_idx, schema, columns)
                if not verified:
                    best_score = score
                    best = Detection(ReportKind.UNKNOWN, row_idx, columns, score,
                                     reason=f"looks like {schema.kind.value}, but {why}")
                    continue
                best_score = score
                best = Detection(schema.kind, row_idx, columns, score)
            else:
                best_score = score
                missing = [s.name for s in schema.required_fields
                           if s.name not in columns]
                best = Detection(
                    ReportKind.UNKNOWN, row_idx, columns, score,
                    reason=(f"closest match was {schema.kind.value} at {score:.0%}; "
                            f"missing column(s): {', '.join(missing)}"))

    if not best.ok:
        # The raw Finacle GL-wise export (SB Order 09/2026 Annexure-III) is a
        # *form*: date and SOL live in a header block, not in columns, so the
        # columnar schemas above can never match it.
        from .glwise_form import detect_form

        layout = detect_form(rows)
        if layout is not None:
            return Detection(ReportKind.FINACLE_GL_WISE, layout.header_row,
                             score=1.0, form=layout)
    return best
