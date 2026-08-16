# SBCO Reconciliation

A Windows desktop application for **SBCO (Savings Bank Control Organisation)** staff at
India Post Head Offices to verify CBS (Finacle) figures against the APT 2.0 Daily Cash
Book, as mandated by **SB Order No. 09/2026**. It replaces the community Excel/VBA
`CASHBOOK_TOOL_for_SBCO` with a proper application backed by a real database.

- `docs/ANALYSIS.md` — breakdown of the SOP and the legacy Excel tool this replaces
- `docs/PLAN.md` — architecture and delivery roadmap

## Features (current)

- **Import** Finacle *GL IT 2.0 GL-Wise Consolidated (Previous Day)* exports (both the
  HO-SOL consolidated and Set-ID per-SOL variants), APT *Daily Cash Book* downloads, and
  APT *Accounting Details* reports (XLS/XLSX) — batch selection, automatic report-type
  detection, duplicate-date and duplicate-file guards, persistent processing summary,
  delete-by-date-range.
- **Daily reconciliation**: Finacle vs Cashbook vs Difference per account code over any
  date range, non-zero filter, datewise drilldown per code, Excel export.
- **Office-wise reconciliation** for one account code: per-SOL Finacle figures vs
  office-wise APT figures, rolled up to SOL groups (BOs compare under their parent SO's
  SOL), with strays flagged when an office or SOL is missing from the master.
- **Monthly report to PAO** (Annexure-IV): Table-1 (Finacle vs Monthly Cash Account
  R/P per code, where Cash Account = Daily Cash Books + approved Transfer Entries) and
  Table-2 (opening/current/rectified/pending differences, carried forward month to
  month, rectifications sourced from the register's settlements) — both exported in the
  exact prescribed layout with DDO/month header, TOTAL row and signature block.
- **Transfer entries** of the DDO, per month, TO (+) / FROM (−).
- **Mismatch heads**: accounted vs cleared vs outstanding for the 8 CBS/IPPB/PLI/Other
  mismatch pairs.
- **Discrepancy Register** (Annexure-IV Table-3): add entries manually or straight from
  the reconciliation view, FY-wise serial numbering that resets each April, settlement
  workflow (rectification date, Misc. Txn / Transfer Entry particulars), Excel export.
- **Masters** seeded from the legacy tool: ~3,000 IT 2.0 account codes, mismatch-head
  pairs (`data/seed/`).
- **Backup/restore** of the SQLite database (WAL-safe online backup).

## Running from source

```bash
pip install -e .[dev]
python -m sbco_recon
```

Data is stored per-user (`%LOCALAPPDATA%\SBCO-Recon` on Windows,
`~/.local/share/SBCO-Recon` elsewhere; override with `SBCO_RECON_DATA_DIR`).

## Tests

```bash
python -m pytest
```

Parsers and reconciliation math are tested against synthetic fixture files whose layout
replicates the real Finacle/APT exports (derived from the legacy tool's VBA and the
report samples in SB Order 09/2026 Annexure-III). Real anonymized exports should be
added to `tests/fixtures/` as they become available.

## Roadmap

See `docs/PLAN.md` — next up: PDF output for the monthly report, the GL IT 2.0
Transaction-report parser as a secondary CBS source, and PyInstaller/Inno Setup
packaging for Windows.
