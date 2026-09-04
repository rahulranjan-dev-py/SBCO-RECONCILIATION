# Changelog

## 2.7.0 — Parity with the legacy tool's real workflow

Derived from a frame-by-frame analysis of a recorded demonstration of
`CASHBOOK TOOL for SBCO 1.09.8` and the VBA of build 1.09.81
(`docs/LEGACY_DEMO_ANALYSIS.md`).

- **Transaction Report as the office-wise source.** The legacy office-wise
  comparison read the Finacle *GL IT2.0 Transaction Report — Consolidated
  (Previous Day)* downloaded with the Set ID, not the GL-wise report. The
  form parser now recognises both titles, the bare "*NNNN - Office*" section
  labels that report uses, and Credit/Debit as well as Deposits/Withdrawals
  headers. Transaction Report data is stored as its own source
  (`FINACLE_TXN`) so it coexists with the daily GL-wise file; the office-wise
  reconciliation prefers it when present.
- **APT Accounting Details, as the portal actually exports it.** The raw
  header is `DEDUCT_DATE | OFFICE_ID | OFFICE_NAME | DATE | ACCT_CODE | AMT |
  REMARKS`; detection now binds the transaction date to `DATE` (never
  `DEDUCT_DATE`), treats `OFFICE_ID` as optional and carries the office
  name, and the office-wise reconciliation matches by name when the ID is
  blank ("Barkur S.O" and "Barkur SO" are the same office).
- **Date-level duplicate guard.** The legacy tool refused a second upload for
  a date it already held ("Duplicate Found: UPLOAD RESTRICTED"). Content
  hashing alone could not: a re-downloaded report differs in its run
  timestamp. A file whose (date, account code) pairs are already loaded for
  that source is now reported as `duplicate`, naming the dates and the upload
  to undo. APT files are keyed per account code, so a different code for the
  same dates still loads.
- **Annexure-IV Table-2 in the interface and the CLI.** Opening balances are
  carried forward from every month the tool holds, oldest first; a one-time
  opening seed (`AC_CODE | DESCRIPTION | RECEIPT_DIFF | PAYMENT_DIFF`, the
  legacy template) covers the first month or a migration from the Excel tool.
  `POST /api/annexure2`, `POST /api/table2-opening`, `sbco annexure --table 2
  [--opening FILE]`.
- **Transfer entries are scoped.** A TE applies either to this month's cash
  account (Table-1) or to an earlier month's pending difference (Table-2's
  *Rectified during the current month*), never both. New `sbco te` command;
  the interface asks which on entry.
- **Office attribution on the register.** Recording discrepancies fills the
  office column from the office-wise figures when they are loaded, in the
  legacy remark style ("Manipal HO (94,000), Barkur SO (40,000)").
- Dashboard code order refreshed from 1.09.81 (same 428 codes, same 3,006
  account codes). Existing databases migrate in place (`entry.office_name`,
  `transfer_entry.scope`, `table2_opening`).
- User guide: the DOP IT 2.0 portal paths as demonstrated (Accounts ▸
  Cashbook ▸ Download Excel; Treasury ▸ Reports ▸ Accounting Details Office
  Wise), `export(n).xls` downloads need no renaming, the office-wise file
  pair, the monthly Table-2 routine.

## 2.6.1 — Smart App Control compatibility

- The Windows bundle's entry point is now **SBCO Reconciliation.exe** — the
  PSF-signed Python interpreter itself, renamed (Authenticode signatures
  cover content, not names). Field testing showed Smart App Control, which
  ships enabled on new Windows 11 machines, hard-blocks internet-downloaded
  `.bat` files with no override; signed executables are allowed. A guarded
  `sitecustomize` hook launches the GUI only on a bare double-click
  (`sys.argv == ['']` and an sbco-named exe); `-m`, `-c` and script runs
  pass through untouched, and `SBCO_NO_AUTOSTART=1` disables the hook.
- Runtime files moved to the bundle root (the interpreter must sit beside
  its DLL and `._pth`); the runtime's own PSF licence is preserved as
  `PYTHON-LICENSE.txt`. `sbco.bat` remains for command-line use on machines
  without Smart App Control.
- The hook exits via `os._exit` — a SystemExit escaping `sitecustomize`
  during `import site` is a fatal interpreter error, and an uncaught
  exception there would strand the user at a bare Python prompt. A GUI
  startup failure now prints a plain-language message, runs the doctor
  report, and waits for Enter before closing. Both behaviours are pinned by
  tests that launch a real interpreter bare, through the actual
  interpreter-init path.
- CI now verifies the renamed exe's Authenticode signature is still valid,
  exercises the double-click autostart path, and runs the full CLI round
  trip through the renamed exe.
- Documentation: "If Windows blocks something" guidance distinguishes
  SmartScreen (More info → Run anyway / Unblock) from Smart App Control
  (no override exists) in the bundle README, the user guide, and the
  troubleshooting table.

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
