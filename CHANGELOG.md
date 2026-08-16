# Changelog

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
