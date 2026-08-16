# Analysis of Source Materials

> Reference document: the requirements analysis of SB Order 09/2026 and the
> legacy Excel/VBA tool that this software replaces. The current architecture
> is described in the repository README.

This document captures what was learned from the two uploaded artifacts, which together
define the problem the new Windows software must solve.

1. **SB Order No. 09/2026** (Dept. of Posts, FS Division, dated 24.07.2026) — the SOP that
   mandates the reconciliation process.
2. **CASHBOOK_TOOL_for_SBCO v1.09.6** (`.xlsb`, ~52k lines of VBA) — the existing
   community-built Excel/VBA tool that implements the process today, and which the new
   software will replace.

---

## 1. The business process (SB Order No. 09/2026)

**Subject:** SOP for Accounting & Verification of POSB accounting at Post Offices after
implementation of APT 2.0. References SB Orders 12/2025 and 16/2025.

### Context

- POSB (Post Office Savings Bank) CBS transactions happen in **Finacle** (HO/SO counters)
  and the **DREAM App** (Branch Offices, BOs).
- These are pushed by API into **APT 2.0** (the accounting application) before Day End, so
  the same day's figures appear in the APT **Daily Cash Book**.
- Sequence per day: transactions → **CSMDAY** in Finacle (HO/SO) / **Close Account** in
  DREAM (BO) → data fetched into APT → Day End in APT.

### Roles and daily duties

| Level | Duty |
|---|---|
| BO (BPM) | Day Begin/Close in DREAM, clear *Pending Transactions*, verify Daily Transaction Report vs BO Daily Account (BODA). Unposted amounts go to **CBS Receipt Mismatch** / **CBS Payment Mismatch** heads — **never netted** against each other. |
| SO/HO counter | All transactions via Finacle between Day Begin and CSMDAY; missing data accounted under the same Mismatch heads; DTR tallied before APT Day End. |
| SO/HO for sub-offices | Verify accounted CBS data in BODA/SODA, reconcile discrepancies in Sub Accounts module, intimate Account Office of mismatch entries. |
| **SBCO at HO (the target user of this software)** | The core daily verification, below. |
| Postmaster | Rectify discrepancies next day via Misc. Transactions / Transfer Entries; adjust mismatch entries through Sub Account module. |
| Divisional/Inspecting authorities | Monitor; verify the Discrepancy Register during inspections. |

### SBCO daily procedure (SOP §4 — the heart of the software)

1. Generate in Finacle MIS: **GL IT 2.0 — GL Wise Report (Incl HO, SO & BOs) — Consolidated
   (Previous Day)** by HO SOL ID. This is the consolidated CBS record for the HO + all
   subordinate offices.
2. Download the **HO Cash Book** for the same date from APT (Excel).
3. Compare Cash Book vs Finacle GL Wise Report, **account-code-wise, daily**.
4. On any discrepancy, generate **GL IT 2.0 — Transaction Report Consolidated (Previous
   Day)** by HO SET ID and drill down against SO Summaries / Daily Accounts to locate the
   exact office and nature of the difference.
5. Report every discrepancy to the Postmaster; record it in a permanent **Discrepancy
   Register** (Annexure-IV Table-3 format).
6. Monitor settlement: watch error-book entries, Transfer Entries posted in APT, and
   Mismatch Adjustment entries; a discrepancy is *settled* only after verifying
   rectification.
7. By the **4th of each month**, submit the **Monthly Report to PAO** in Annexure-IV
   **Table-1 and Table-2** formats, jointly signed by In-charge SBCO and Postmaster.
   *Monthly Cash Account = sum of Daily Cash Books + approved Transfer Entries of the DDO.*
   Monthly SOL-wise/date-wise/account-code-wise Finacle data is provided by the CBS Reports
   Team over SFTP (retained max 3 months).

### Prescribed output formats (Annexure-IV)

- **Table-1** — monthly, per account code: Finacle Receipts/Payments, Monthly Cash Account
  Receipts/Payments, Difference (Finacle − Cash Account) R/P, with totals, DDO code, month,
  signature blocks.
- **Table-2** — monthly, per account code: Opening Balance of difference, Current Month
  Difference, Rectified During Month, Pending for Rectification (each as R/P pairs), plus
  reasons for pendency and target clearance date.
- **Table-3** — the CBS Daily Discrepancy Reconciliation Register: Sl No, Date, Account
  Code + description, office where found, Receipt/Payment as per CBS, as per Cash Book,
  differences (f−h, g−i), initials, date of rectification, particulars of Misc.
  Transaction / Transfer Entries posted, PA/APM and Postmaster initials. Serial number
  resets each financial year. Preserved permanently.

### Input reports available (Annexure-III)

From Finacle production server (same day) and MIS server (previous days), in PDF or XLS:

- GL IT 2.0 Transaction Report — Consolidated (by Set ID/SOL ID, BO code, channel)
- GL IT 2.0 Transaction Report — Detailed
- GL IT 2.0 Report GL Wise — Consolidated (by HO SOL ID; includes HO, SO & BOs)

The GL-wise report's tabular body is: S.No, GL Sub Head Code, IT2.0 A/C Code, IT2.0 Acct
Code Desc, Deposits (Cr), Withdrawals (Dr).

---

## 2. The existing Excel/VBA tool (CASHBOOK_TOOL_for_SBCO v1.09.6)

A 27-sheet `.xlsb` with a large VBA project (forms, ~60 modules/sheets, protected sheets,
hidden internals). Described in its HELP sheet as: *"This tool can be used to find
discrepancies / non-accounted CBS figures in APT 2.0 cashbook. Free to use, offered as-is."*

### Data model (hidden "database" sheets)

| Sheet | Role | Columns |
|---|---|---|
| `TEMP` | staging area for every uploaded file | raw paste |
| `TEMP.FIN` | Finacle GL-wise daily data store | DATE, ACCOUNT CODE, DESCRIPTION, AMT |
| `TEMP.CBR` | APT Cashbook daily data store | Date, Office Name, Office ID, Account Code, Description, Part, Receipts/Payments, HO, SO, BO, Total, Progressive Total |
| `TEMP.FIN.GL` | GL-wise per-SOL data (office-wise recon) | DATE, SOL ID, OFFICE, ACCOUNT CODE, DESCRIPTION, RECEIPT, VALIDATOR |
| `TEMP.FIN.TR` | Transaction-report data | DATE, SOL ID, ACCOUNT CODE, DESCRIPTION, AMT |
| `TEMP.CLR` | APT clearing/accounting-details data | OFFICE ID, OFFICE, DATE, ACCOUNT CODE, AMOUNT, DESCRIPTION, SOL ID, VALIDATOR |
| `TEMP.CLRNG.AC` | mapping of the 8 mismatch heads to their "cleared" counterparts | e.g. 8671002400 CBS Receipts Mismatch ↔ 8671002500 Cleared |
| `APT_ALL` | manual/APT entries | DEDUCT_DATE, OFFICE_ID, OFFICE_NAME, DATE, ACCT_CODE, AMT, REMARKS |
| `TE_DATA` | Transfer Entries per month | MONTH, AC_CODE, AC_DESC, FROM(−)/TO(+), plus HO/DVN/DDO header |
| `OFFICE_DATA` | office master | OFFICE_NAME, OFFICE_ID, SOL_ID/BO_CODE, SOL_ID_GROUP (BOs map to parent SO's SOL) |
| `ac_codes` | account-code master, ~3,000 rows | account_code, HOA, description, Receipt/Payment side, sign, Part I/II/III |
| `VALIDATOR` | quarter/date validation tables | FY quarters with start/end dates |

### Report/UI sheets

- `CBS` — the main daily reconciliation: per account code, *Finacle DATA* vs *Cash Book
  DATA* vs *Difference* over a FROM/TO date range; auto-filtered to non-zero.
- `compare.glwise.report` / `compare.transaction.report` — office-wise reconciliation for a
  single account code: FINACLE DATA vs APT DATA vs DIFFERENCE per office (APT side fed from
  Treasury → Reports → Accounting Details).
- `CLRAC` — clearing-account reconciliation: ACCOUNTED vs CLEARED amount per head.
- `MISMATCH ENTRIES` — summary for the 8 mismatch heads: Mismatch Amt, Cleared Amt, Difference.
- `DATEWISE_DATA` — day-by-day drilldown for one account code over a range.
- `DESC.RPT` — the Discrepancy Register (add via form, search duplicates, view, print,
  export, FROM/TO filter).
- `CBS-MRR-TABLE1` / `CBS-MRR-TABLE2` — Annexure-IV Table-1 generation (incl. TE data),
  export.
- `Processing Summary` — per-file batch upload audit (file name, status, time, totals).
- `HELP`, office-data management UI, admin/backup-restore.

### Key VBA behaviors worth replicating (and improving)

- **Batch upload with validation**: user multi-selects Finacle XLS exports; each file is
  opened, values pasted to `TEMP`, then validated by a **fingerprint cell** — e.g. cell I4
  must equal `"GL IT2.0 Transaction GL Wise Report (Incl HO,SO &BOs) -
  Consolidated(Previous Day)"`; the report date is read from F8 (dd-mm-yyyy) and stamped on
  every row. Invalid files are logged and skipped.
- **Transform pipeline** (`cashbook_finacledata_1..7`): stamp date → drop layout columns
  (A:H, L:P, R:T) → drop blank rows → **merge Deposits + Withdrawals into a single AMT**
  (receipts and payments are separate account codes in IT 2.0, so one amount column
  suffices) → **duplicate-date guard** (refuses re-upload of an already-loaded date) →
  append to store → refresh filters.
- **Cashbook upload**: similar; drops the 2 header rows, reads date from A4, appends 13
  columns to `TEMP.CBR` with the same duplicate-date guard.
- **Deletion tools**: delete-all and delete-by-date-range per data store.
- **Backup/restore** of all data sheets (restore supports ≥ v1.09.1).
- Sheet protection everywhere with a hardcoded password (`suraj`) and hidden/very-hidden
  sheets to simulate an application shell — a strong sign the workflow has outgrown Excel.

### Pain points of the current tool (why a real Windows app is justified)

1. Excel + VBA fragility: file corruption, macro security prompts, version differences,
   protection tricks, everything in one `.xlsb` that is both program and database.
2. Data volume: sheets like `TEMP.FIN.GL` already hold 13k+ rows; a year of daily data for
   a large HO strains Excel and the O(n) VBA loops.
3. No real database: duplicate-date logic, deletes and filters are hand-rolled; no
   integrity, no audit trail beyond one summary sheet.
4. Single-user, single-file; sharing means emailing the whole workbook.
5. Manual multi-step UX (upload buttons per report type, hidden sheet navigation).
6. Reporting is limited to Excel prints; Annexure-IV Table-2 (opening/rectified/pending
   balances) appears only partially automated.

---

## 3. Reconciliation logic to implement (distilled)

```
Daily, per account code (HO consolidated):
    finacle_amount  = Σ (Deposits + Withdrawals) from GL-wise report rows for that code
    cashbook_amount = Σ Total from APT cashbook rows for that code
    difference      = finacle_amount − cashbook_amount   → 0 means reconciled

Office-wise drilldown (for a chosen account code and range):
    per office (SOL ID group; BO rolls up to parent SO SOL):
        finacle (GL-wise or transaction report) vs APT accounting-details → difference

Clearing / mismatch heads (8 pairs, codes 86710024xx–86710039xx):
    accounted (mismatch head) vs cleared (counterpart head) → outstanding

Datewise drilldown (account code): per-day finacle vs cashbook over a range.

Register: every non-zero difference becomes a Discrepancy Register entry
    (Table-3 columns), tracked to settlement; serials reset each FY.

Monthly (Annexure-IV):
    Table-1: per code, Finacle R/P vs (Σ daily cashbooks + approved TEs) R/P + difference
    Table-2: opening diff, current-month diff, rectified, pending (R/P each)
```

Receipts and payments are distinct account codes (e.g. `8001000100` POSB Receipts /
`8001000200` POSB Payments), so "never net receipts against payments" is naturally enforced
by comparing at account-code level. The `ac_codes` master carries the Receipt/Payment side,
sign and Part for report classification — this master (~3,000 codes) and the mismatch-head
mapping should be seeded into the new application's database from the workbook.

### Note on the tutorial video

The YouTube link could not be fetched from this environment (network egress blocked). The
workflow above was reconstructed from the SOP, the tool's HELP sheet (which also links two
Google Drive tutorial videos), and a full read of the VBA source, which is authoritative
for what the tool actually does.
