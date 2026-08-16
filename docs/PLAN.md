# SBCO Reconciliation — Windows Software Plan

Goal: replace the Excel/VBA `CASHBOOK_TOOL_for_SBCO` with a proper offline Windows
application that implements SB Order No. 09/2026 end-to-end for SBCO staff at Head Post
Offices: import Finacle & APT reports, reconcile daily, maintain the Discrepancy Register,
and produce the prescribed Annexure-IV outputs.

See `docs/ANALYSIS.md` for the full breakdown of the SOP and the existing tool.

---

## 1. Product scope

### Users & constraints

- SBCO PAs / In-charge at HOs; also usable by Divisional offices for oversight.
- Government Windows PCs (Windows 10/11), frequently **offline**, often without admin
  rights → must run as a **portable app or per-user installer**, no server dependency.
- Inputs are XLS/XLSX exports from Finacle MIS and APT 2.0 (occasionally PDF; out of scope
  initially). Single-user per HO; the database is one file that can be backed up/shared.

### Core features (functional parity with the Excel tool, then beyond)

1. **Report imports** with format fingerprinting, batch multi-file selection,
   per-file audit log, duplicate-date protection, delete by date range:
   - GL IT 2.0 GL-Wise Report — Consolidated (Previous Day) — daily CBS side
   - APT Daily Cash Book (XLS download) — daily cashbook side
   - GL IT 2.0 Transaction Report — Consolidated — office-wise drilldown
   - APT Treasury → Accounting Details — per-account-code office-wise APT side
   - Manual entries (same fields as the tool's manual-data form) and Transfer Entries
2. **Reconciliation views**
   - Daily account-code-wise: Finacle vs Cashbook vs Difference, date-range filter,
     non-zero-only toggle (parity with the `CBS` sheet)
   - Datewise drilldown for one account code
   - Office-wise reconciliation for one account code (GL-wise and transaction-report
     variants)
   - Clearing/mismatch heads: accounted vs cleared vs outstanding for the 8 pairs
3. **Discrepancy Register** (Annexure-IV Table-3): auto-create entries from non-zero
   differences (with confirm), manual add/edit, settlement workflow (date of rectification,
   Misc. Transaction / TE particulars), FY-wise serial reset, permanent history, print/export.
4. **Monthly reporting**: Annexure-IV **Table-1** and **Table-2** generation for a chosen
   month (Monthly Cash Account = Σ daily cashbooks + approved TEs), export to Excel/PDF
   with DDO code, month, signature blocks.
5. **Masters**: office master (HO/SO/BO with SOL-ID grouping), account-code master
   (~3,000 codes seeded from the existing tool), mismatch-head pairs, DDO/HO profile.
6. **Utilities**: backup/restore of the database, import of data from the existing
   `.xlsb` tool (its backup format ≥ v1.09.1), processing-summary audit trail.

### Non-goals (v1)

- No direct Finacle/APT/SFTP connectivity (files are imported manually).
- No multi-user concurrent editing or central server; no PDF report parsing.

---

## 2. Recommended architecture

### Tech stack (recommendation)

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Maintainer familiarity; rich Excel ecosystem |
| UI | **PySide6 (Qt Widgets)** | Native-feeling Windows desktop UI, table views, printing support |
| Database | **SQLite** (via SQLAlchemy) | Single-file, zero-install, transactional, handles years of daily data trivially |
| Excel I/O | `xlrd` (legacy BIFF `.xls` from Finacle/APT), `openpyxl` (`.xlsx` read + report export), `pandas` for transforms | Matches the real input formats |
| PDF export | `reportlab` (Annexure-IV, register prints) | Offline PDF generation |
| Packaging | **PyInstaller one-folder build + Inno Setup per-user installer** (also runnable as a portable folder) | No admin rights needed |

Alternative considered: C# .NET 8 + WPF (excellent Windows fit, single-exe publish) — worth
switching to only if Python distribution proves problematic; the plan's architecture is
stack-agnostic (UI ↔ service layer ↔ SQLite).

### Application layers

```
ui/           Qt windows & dialogs (dashboard, imports, recon views, register, reports, masters)
services/     import pipeline, recon engine, register workflow, report builders, backup
parsers/      one module per report format, each with: fingerprint(), extract() → normalized rows
db/           SQLAlchemy models + migrations (alembic), seed data (ac_codes, mismatch pairs)
export/       xlsx/pdf renderers for Annexure-IV T1/T2/T3 and view exports
```

### Data model (main tables)

- `offices(id, name, office_id, sol_or_bo_code, sol_group)`
- `account_codes(code, hoa, description, side, sign, part)` — seeded
- `mismatch_pairs(mismatch_code, cleared_code, label)` — seeded (8 pairs)
- `finacle_gl_daily(date, account_code, amount)` — from GL-wise consolidated
- `finacle_gl_solwise(date, sol_id, office_id, account_code, amount)`
- `finacle_txn(date, sol_id, account_code, amount)` — transaction report
- `cashbook_daily(date, office_id, account_code, part, side, ho_amt, so_amt, bo_amt, total)`
- `apt_accounting_details(date, office_id, account_code, amount)`
- `manual_entries(...)`, `transfer_entries(month, account_code, direction, amount)`
- `discrepancy_register(fy, serial, date, account_code, office, cbs_r, cbs_p, cb_r, cb_p, status, rectified_on, misc_txn, te_ref, remarks, ...)`
- `import_log(file_name, report_type, report_date, status, row_count, imported_at, checksum)`

Uniqueness guards move from VBA loops to DB constraints (e.g. unique
`(report_type, date)` in `import_log` enforces the duplicate-date rule; checksums catch
re-named re-uploads).

### Import pipeline (replaces `cashbook_finacledata_*` / `cashbook_cashbookreport_*`)

1. User multi-selects files → each parsed in memory (never opens Excel itself).
2. `fingerprint()` identifies the report type from known header cells (same strings the
   VBA checks, but tolerant of position drift with a search window).
3. `extract()` returns normalized rows + the report date; validation errors collected per
   file, not fatal to the batch.
4. Duplicate-date/checksum guard → transactional insert → import-log entry.
5. Live processing summary (parity with the `Processing Summary` sheet).

### Reconciliation engine

Plain SQL aggregations (per the distilled logic in ANALYSIS §3), returned as dataframes to
the UI: daily code-wise, datewise, office-wise, clearing-heads, monthly rollups. All views
export to XLSX; register and annexures also to PDF.

---

## 3. Delivery roadmap

| Phase | Deliverable | Contents |
|---|---|---|
| **0. Foundation** | runnable skeleton | repo layout, PySide6 app shell, SQLite schema + migrations, seeds (ac_codes, mismatch pairs, model offices), settings/profile screen |
| **1. Daily recon MVP** | first useful build | GL-wise + cashbook parsers, batch import with audit & duplicate guard, daily account-code recon view + datewise drilldown, XLSX export, DB backup/restore |
| **2. Drilldown & clearing** | parity with Excel tool | transaction-report + accounting-details parsers, office-wise recon views, clearing/mismatch dashboard, manual entries & TEs, delete-by-range tools |
| **3. Register & monthly reports** | compliance outputs | Discrepancy Register with settlement workflow + FY serials, Annexure-IV Table-1/2/3 export (XLSX + PDF), print support |
| **4. Packaging & migration** | distributable | PyInstaller + Inno Setup builds, `.xlsb` data migration importer, user guide with screenshots, sample anonymized test files, versioned releases |

Each phase ends with tests against fixture files (synthetic Finacle/APT exports checked
into `tests/fixtures/`) so parsers and recon math are regression-proof.

---

## 4. Open questions for the product owner

1. **Sample files**: real (anonymized) exports of the four input reports are needed to
   pin down exact layouts — the VBA gives column positions, but fixtures make it certain.
   Priority: GL-wise consolidated XLS and APT cashbook XLS.
2. **Annexure-IV Table-2 opening balances**: confirm the rule for carrying forward
   month-opening differences (from prior month's pending, per code).
3. Single HO per database, or should one install support multiple HOs (profiles)?
4. Any Hindi/bilingual UI or report requirement?
5. Confirm the Python/PySide6 stack choice (vs .NET/WPF) before Phase 0 starts.
