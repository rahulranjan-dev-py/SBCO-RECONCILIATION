# Changelog

## 2.6.0 — Windows packaging

- Released under the MIT license; LICENSE.txt ships inside the Windows bundle.
- Portable Windows package: extract-and-double-click, no installer, no admin
  rights, no Python on the PC. Built around python.org's official embeddable
  CPython (version- and SHA-256-pinned), with the application and all
  dependencies vendored in. A plain folder rather than a frozen single .exe,
  deliberately: self-extracting freezers are routinely quarantined by
  departmental antivirus policy.
- Windows CI: the full test suite runs on `windows-latest` (normal and with
  assertions stripped), the package is built, and the **bundled** runtime is
  smoke-tested end to end — doctor, load, reconcile, register, Table-3
  export. The zip is uploaded as an artifact on every push and attached to
  the GitHub release on `v*` tags.

## 2.5.0 — The register becomes a maintained record

- Table-3 (CBS Daily Discrepancy Reconciliation Register) is now recorded,
  listed, settled and exported — previously only the export layout existed.
- Serial numbers are assigned transactionally per financial year and restart
  from 1 each April, per the order's footnote.
- **Save to register** recomputes the period's differences server-side,
  splits Receipt/Payment by the account-code master, and skips codes already
  open for the same date — a double press cannot double-enter.
- Settlement requires the rectification particulars (Misc. transaction and/or
  transfer entry) and the date; a second settlement, or one dated before the
  entry itself, is refused.
- New Register screen (FY selector, open/settled filter, ageing, inline
  settle) and `sbco register` CLI command.

## 2.4.0 — Raw Finacle GL-wise exports

- The GL-wise report as Finacle actually emits it (SB Order 09/2026,
  Annexure-III) is a *form*: date and SOL in a label/value header block,
  amounts split into Deposits (Cr) / Withdrawals (Dr), one section per SOL in
  Set-ID reports. The columnar detector could not match that shape; it is now
  detected and parsed automatically, with the header date and each section's
  SOL stamped onto every row — so a single Set-ID upload also feeds the
  office-wise reconciliation.
- Verified against the order's own page-11 sample figures.

## 2.3.1 and earlier — The engine rebuild

- Ground-up rebuild of the `CASHBOOK_TOOL_for_SBCO` Excel/VBA workbook as a
  tested Python engine: SQLite store with atomic batches, SHA-256 dedupe and
  per-batch reversal; Decimal-exact amounts; locale-independent day-first
  parsing; header-driven report detection with content verification; coverage
  warnings when a day has no report; the browser interface and CLI over one
  shared engine; Annexure-IV Tables 1 and 2; reference data (3,006 account
  codes, dashboard ordering, eight clearing pairs) recovered from the
  original workbook; regression suites pinning the legacy defects and QA
  findings shut, including HTTP-level security tests.
