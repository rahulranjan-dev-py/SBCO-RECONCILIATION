<!-- Reference document. A frame-by-frame analysis of a recorded demonstration of
     the legacy Excel/VBA workbook this project replaces. Kept in the repository
     because several v2.7 behaviours (portal paths, the Transaction Report as the
     office-wise source, the date-level duplicate guard, Table-2 carry-forward)
     were derived from it. The recording's author has been removed. -->

# CASHBOOK TOOL for SBCO v1.09.8 — Operational Demo Analysis

**Source:** Silent 58‑minute screen recording (1152×720 @ 60 fps, no audio track content), Windows 11, Excel 365 (plus Excel 2007 for scratch files). Recorded 16‑08‑2026 10:37–11:35 by an SBCO user at a Head Office (Udupi Division).
**Analysis method:** 351 frames sampled every 10 s, OCR on every frame, full‑resolution review of ~40 key screens.
**Artefact under demo:** `CASHBOOK TOOL for SBCO 1.09.8.xlsb` — macro‑enabled binary Excel workbook with a VBA‑driven button UI. Earlier build `1.09.7` and sibling tools (`TD Incentive tool 1.03 / 1.07`, `CBS‑MRR‑TABLE1/2`, `BO Int. Entry register`) also visible on the desktop.

---

## 1. Purpose of the tool

An Excel/VBA reconciliation utility for India Post **SBCO (Savings Bank Control Organisation)**. It:

1. Ingests daily **Finacle CBS "GL IT2.0 Transaction GL Wise Report (Incl HO, SO & BOs) – Consolidated"** exports.
2. Ingests daily **DOP IT 2.0 Cashbook** exports (Accounts ▸ Accounts Consolidation ▸ Cashbook ▸ Download Cashbook (XLS)).
3. Compares the two per GL account code over a date range and highlights differences.
4. Lets the user drill down to **date‑wise** and then **office‑wise** (HO/SO/BO) level using the DOP IT 2.0 **Treasury ▸ Accounting Details Office Wise (APT)** report and the **GL IT2.0 Transaction Report – Consolidated (Previous Day) with SET ID** report.
5. Records findings in a **Discrepancy Report** register with free‑text remarks.
6. Generates the monthly **CBS Monthly Reconciliation Report to PAO by the HO — Annexure‑IV Table‑1 and Table‑2** (due 4th of every month), including approved Transfer Entries (TE).

External systems used during the demo: `https://app.indiapost.gov.in` (DOP IT 2.0 web portal, Waterfox browser), pages `/subaccounts/post-cash-book`, `/treasury/accounting-details`, `/treasury/landing`, `/subaccounts/home`.

---

## 2. Workbook structure

### 2.1 Sheets observed

| Sheet | Role |
|---|---|
| `CBS` | Home dashboard: upload buttons, date range, main comparison table (~975 GL codes) |
| `TEMP.FIN` | Staging table for **Finacle CBS GL** rows (A = date, D = A/C code, K = amount) |
| `TEMP.CBR` | Staging table for **Cashbook** rows (same layout) |
| `TEMP.CLR` | Staging table for the **office‑level (SET‑ID/SOL) CBS "Consolidated (Previous Day)"** report (A = SOL/office id, C = date, D = A/C code, E = amount) |
| `Processing Summary` | Batch‑upload log (file name, status, time, totals) — has a `RETURN` button |
| `DATEWISE_DATA` | Drill‑down for one A/C code: DATE / FINACLE DATA / CASHBOOK DATA / DIFFERENCE |
| `compare.transaction.report` | Office‑wise reconciliation for one A/C code & one date: OFFICE / FINACLE DATA / APT DATA / DIFFERENCE |
| `OFFICE_DATA` | Office master: OFFICE_NAME, OFFICE_ID, SOL_ID/BO_CODE, SOL_ID_GROUP |
| `DESC.RPT` | Discrepancy report / register with REMARKS |
| `DESC.` | Helper/scratch sheet (seen briefly, mostly blank) |
| TE list sheet (name cut off, "TE_DATA"‑like) | MONTH / AC_CODE / AC_DESC / FROM(‑)/TO(+) — approved Transfer Entries, `GO BACK` button, warning "DO NOT DELETE THIS ROW" |

Hidden/temp sheets are toggled on/off by the macros; the tab strip normally shows only `CBS` plus whichever report sheet is active.

### 2.2 Key formulas seen in the formula bar

```excel
' CBS!D (Cash Book DATA) – row‑wise, table structured reference
=SUMIFS(TEMP.CBR!$K:$K, TEMP.CBR!$D:$D, [@[AC CODE]],
        TEMP.CBR!$A:$A, ">="&CBS!$E$3, TEMP.CBR!$A:$A, "<="&CBS!$E$4)

' CBS!C (Finacle DATA) – same pattern against TEMP.FIN
=SUMIFS(TEMP.FIN!$K:$K, TEMP.FIN!$D:$D, [@[AC CODE]],
        TEMP.FIN!$A:$A, ">="&CBS!$E$3, TEMP.FIN!$A:$A, "<="&CBS!$E$4)

' CBS!E (Difference)
=IFERROR(C360-D360,"")

' DATEWISE_DATA!D (Cashbook per date)
=SUMIFS(TEMP.CBR!$K:$K, TEMP.CBR!$D:$D, DATEWISE_DATA!$E$4, TEMP.CBR!$A:$A, [@DATE])

' compare.transaction.report!B (Finacle per office)
=SUMIFS(TEMP.CLR!$E:$E,
        TEMP.CLR!$A:$A, VLOOKUP([@OFFICE], OFFICE_DATA!A:C, 2, 0),
        TEMP.CLR!D:D, $C$2,
        TEMP.CLR!C:C, ">="&$B$1, TEMP.CLR!C:C, "<="&$C$1)

' compare.transaction.report!D (Difference)
=[@[FINACLE DATA]]-[@[APT DATA]]

' compare.transaction.report!E1 (dynamic source caption)
="finacle MIS >> GL IT2.0 Transaction Report - Consolidated(Previous Day), Date : "
 &TEXT(C1,"dd/mm/yyyy")&", and SET ID"

' compare.transaction.report!E2
="Treasury >> Reports >> Accounting Details >>A/c Code : "&C2&", from : "
 &TEXT(B1,"dd-mm-yyyy")&" to : "&TEXT(C1,"dd-mm-yyyy")&", office : all, Generate (XLS)"
```

Difference cells are conditionally formatted (pink fill, red text) when ≠ 0.

---

## 3. Home dashboard (`CBS` sheet) — controls

**Upload area (rows 1‑3)**
- `CBS REPORT :` caption "GL IT2.0 Transaction GL Wise Report (Incl HO,SO &BOs) – Consolidated" → `UPLOAD FILES ->` (green Excel icon; multi‑select `.xls`).
- `CASHBOOK :` caption "Accounts >> Accounts Consolidation >> Cashbook >> Download Cashbook (XLS)" → `UPLOAD FILES ->`.
- `COMPARE DATA` (large blue button), `REMOVE FILTER`.
- `DATE RANGE` panel: `FROM:` / `TO:` cells (E3, E4) with calendar icons that open a **"Select Date" month‑grid picker** popup.

**Main table (row 5 header)**
AC CODE (`SORT` + autofilter) | DESCRIPTION | Discrepancy Report: `ADD` / `VIEW` | Finacle DATA (`SORT`, `FILTER`) | Cash Book DATA | Difference (`VIEW ALL`, `FILTER`).
Clicking a Finacle/Cashbook value cell opens the **SELECT A/C CODE** popup (see §5.4).

**Right‑hand panel**
- DELETE : CBS Report → `DATE RANGE`, `DELETE ALL`
- DELETE : Cash Book → `DATE RANGE`, `DELETE ALL`
- CBS Monthly Reconciliation Report → `Annexure‑IV TABLE‑1`, `Annexure‑IV TABLE‑2`
- DATA → `BACKUP`, `RESTORE`
- OTHERS → `ABOUT`, `HELP`
- `OFFICE SETTINGS`
- "COMPARE DATA: Pages" → `GL wise DATA` (navigation to the office‑wise sheet)

---

## 4. Demonstrated workflow — chronological

Times are video offsets (mm:ss) → wall clock on the recording.

### Phase A — Setup (00:00–01:50, 10:37)
1. Excel start screen → Open → `Desktop\CBS RECON\CASHBOOK TOOL for SBCO 1.09.8.xlsb`.
2. Protected View bar → **Enable Editing**. Second bar "SECURITY RISK: Microsoft has blocked macros from running because the source of this file is untrusted".
3. Fix: File ▸ Options ▸ Trust Center ▸ Trust Center Settings ▸ **Trusted Locations ▸ Add new location** → browse to the tool folder → OK. Macro Settings tab also shown (Disable VBA macros with notification).
4. Reopen; buttons now work.

### Phase B — Upload CBS (Finacle) report (01:50–02:40)
5. `UPLOAD FILES ->` (CBS row) → "Select CBS Report Files (Multiple Selection Allowed)" dialog → folder `…\FINACLE\GL IT2.0 Transaction GL Wise Report (Incl HO,SO &BOs) – Consolidated\` → files `01 07 2026.xls … 31 07 2026.xls` (27 files, 44–48 KB each, Excel 97‑2003) → Open.
6. Status bar shows `File 27/28 | Macro 7/7`; completion dialog:
   > **Complete** — Batch Processing for CBS report is Complete! Total Files Selected: 27, Successfully Processed: 27, Failed/Invalid: 0, Processing Time: 00:00:34. See 'Processing Summary' sheet for details.
7. `Processing Summary` sheet: File Name | Status (`PROCESSED` in green) | Processed Time, followed by TOTAL FILES SELECTED / PROCESSED SUCCESSFULLY / FAILED‑INVALID / TOTAL PROCESSED / PROCESSING TIME / Completed timestamp; `RETURN` button.

### Phase C — Duplicate guard (02:40–03:00)
8. Re‑selecting an already‑loaded file →
   > **Duplicate Found: UPLOAD RESTRICTED** — Data already available for the Date: 01‑07‑2026. Number of entries : 122.
   Status bar `File 2/32 | Macro 2/2`. Duplicate check is keyed on the report date inside the file, not on file name.

### Phase D — Compare (03:00–04:00)
9. FROM `01‑07‑2026`, TO `31‑07‑2026` → `COMPARE DATA`. Table refreshes; Cashbook side still 0 (not yet uploaded), so every Finacle value shows as a difference.

### Phase E — Download Cashbook from DOP IT 2.0 (04:00–05:30, 10:43)
10. Browser → `app.indiapost.gov.in/subaccounts/home` (dashboard tiles: SO Slips and Bags, Accounts Verification, Error Management, Accounts Consolidation, ECB Management, Reports; KPIs "Errors Pending 0", "ECB Not Reviewed 1449", "Cashbook Not Generated 2", "Cashbook Not Submitted to PAO 0").
11. Accounts ▸ Cashbook page (`/subaccounts/post-cash-book`): buttons `View Verification Status (#)`, `View CashBook OB/CB`, `View Cashbook Status`; 3‑step wizard **Step 1 Submit Accounts to Cashbook → Step 2 View/Download Cashbook → Step 3 Submit cashbook to PAO**.
12. Step 2: pick Date (08/07, 28/07, 29/07/2026 shown) → `Download Cashbook` → `Download Excel` → toast "Cash Book fetched successfully". Browser saves as `export(n).xls` in Downloads (Excel 97‑2003, ~44 KB).
13. Files moved into the working tree: `manipal ho cbs\REPORTS\JULY26\CASHBOOK\` (renamed `export (19).xls … export (45).xls`). Sibling folders seen: `REPORTS\JULY26\FINACLE\<report name>\`, `REPORTS\JULY26\apt\`, `REPORTS\AUGUST 2026\`, `BACKUP\`.

### Phase F — Upload Cashbook (05:30–07:00)
14. `UPLOAD FILES ->` (CASHBOOK row) → "Select CashBook Report Files (Multiple Selection Allowed)" → 4 files `export(8)…export(11).xls`. Progress text "Processing file 4 of 5 (0 valid 3 invalid)" seen mid‑run; summary sheet then shows 4 selected / 4 processed / 0 failed / 00:00:07.
15. `COMPARE DATA` again → most rows now 0; residual differences (A/C codes 8782005200, 1201013600, 1201013800, 8661000900/1000, 8008005900/5700, 9421000500, 8446015800, 8661006300, 8001002700, 8001000300, 8001000200) remain.

### Phase G — Date‑wise drill‑down (07:30–08:00, 10:47)
16. Click difference on 8782005200 → **`DATEWISE_DATA`** sheet: header FROM/TO/AC CODE; rows filtered to the account; `HOME PAGE` button. Example: 30‑07‑2026 Finacle 13,40,000 / Cashbook 0 → diff 13,40,000. Status bar "1 of 975 records found" (table holds all dates × codes; autofilter narrows it).

### Phase H — Office settings (08:00–09:30, 10:48)
17. `OFFICE SETTINGS` → **`OFFICE_DATA`** sheet with `GET TEMPLATE`, `IMPORT DATA`, `SAVE`, `RESET`, `HOME`. Ships with placeholder rows `MODEL OFFICE HO / 1 SO / 1.1 BO / 1.2 BO / 2 SO / 2.1 BO / 2.2 BO` (IDs 12345600‑06, SOL 58345610‑12).
18. `IMPORT DATA` → browse `office settings.xlsx` (Sheet1, ~60 rows: e.g. Haluvalli BO 21107595 G2878 57621501; Dist Offices Complex Manipal SO 21661551 57610401; Hiriadka SO 21661558 57611301 …). Columns map to OFFICE_NAME / OFFICE_ID / SOL_ID‑BO_CODE / SOL_ID_GROUP. `SAVE` → `HOME`.

### Phase I — Office‑wise reconciliation (09:30–12:00, 10:49)
19. From DATEWISE_DATA / SELECT A/C CODE → `COMPARE WITH IT 2.0 TRANSACTION REPORT` → **`compare.transaction.report`** sheet.
    Header: title "OFFICE WISE RECONCILIATION (GL IT2.0 Transaction report)", date From/To (with date pickers), ACCOUNT CODE, CBS REPORT caption + `UPLOAD FILE ->` / `DELETE ->` / `BULK UPLOAD ->`, APT REPORT caption + `UPLOAD FILE ->` / `DELETE ->`.
    Nav buttons: `HOME`, `Compare with GL wise report`, `OFFICE SETTINGS`, `Descrepancy Reports` [sic]. Tools: `REMOVE FILTER`, `PRINT`.
    Table: OFFICE | FINACLE DATA | APT DATA | DIFFERENCE, one row per office from OFFICE_DATA.
20. Upload the Finacle **"GL IT2.0 Transaction Report – Consolidated (Previous Day)"** file for the date (folder `FINACLE\GL IT2.0 Transaction Report - Consolidated(Previous Day)\JULY 2026\`) → dialog "DATA process complete".
21. In the portal: Treasury ▸ Reports ▸ **Accounting Details Office Wise** (`/treasury/accounting-details`): Select Type (Receipt / Payment / Transaction Type), Account Code (typed description, e.g. "POSB_Cheque Book Issuance Fee"), From/To date, Select Office (All / individual) → `Generate` → grid (Office Name, Transaction Date, Remarks, Total Transactions, Total Amount) → `Download Excel` (`export(n).xls`, ~2 KB) / `Print`.
22. Upload that file via APT `UPLOAD FILE ->`. Result example (8782005200, 30‑07‑2026): Manipal HO Finacle 94,20,000 vs APT 0; Barkur SO Finacle 0 vs APT 42,00,000 → offices identified.
23. Validation message when the wrong APT file is chosen: **"REPORT IS NOT BELONG TO A/C CODE : 8008005700"** — the tool checks the account code embedded in the APT export.

### Phase J — Discrepancy register (12:00–13:30, 10:50)
24. `Descrepancy Reports` / `VIEW` → **`DESC.RPT`** sheet. Buttons: `EXPORT`, `PRINT`, `DELETE ALL`, `SAVE`, `UNLOCK`, `HOME PAGE`, `GL wise DATA`, `Transaction report DATA`. Columns: FROM | TO | A/C CODE | DESCRIPTION | CBS DATA | APT DATA | DIFFERENCE | REMARKS. Rows are added from the home sheet `ADD` button (one per differing A/C code for the range). Sheet is locked; `UNLOCK` allows editing REMARKS.
25. Remarks entered by hand, e.g. `date : 30.07.2026, Manipal H.O (94000), Barkur S.O (40000)`.

### Phase K — Repeat loop for every residual difference (13:30–50:00)
For each code: home → click value → SELECT A/C CODE popup → `DATEWISE SUMMERY` → note date(s) → `COMPARE WITH IT 2.0 TRANSACTION REPORT` → set date → upload Finacle previous‑day report (if not already) → portal APT report for that code/date → upload → read office → `Descrepancy Reports` → remark. Codes covered and final remarks:

| A/C code | Description | Diff | Remark recorded |
|---|---|---|---|
| 8782005200 | RSAO_POSB_NEFT & RTGS_Amount received by CPRC | 13,40,000 | date : 30.07.2026, Manipal H.O (94000), Barkur S.O (40000) |
| 1201013600 | POSB_Cheque Book Issuance Fee | 40 | date : 22.07.2026, Saligrama S.O (40) |
| 1201013800 | POSB_Pledging Fee | −40 | date : 13.07.2026, DC Offfice S.O (‑15), date : 22.07.2026, Hangarkatta S.O (‑22) |
| 8661000900 | CGST‑Collection on Banking and Finance Services | 4 | date : 22.07.2026, Saligrama S.O (4) |
| 8661001000 | SGST‑Collection on Banking and Finance Services | 4 | date : 22.07.2026, Saligrama S.O (4) |
| 8008005900 | SSA Default Fee | 6,550 | TE SSA DF (+6550) |
| 8008005700 | RD Default Fee | 15 | date : 31.07.2026, Santhekattekalathur B.O (15) |
| 9421000500 | IT TDS from Commission, Brokerage under 194‑H | −7,22,920 | date : 13.07.2026, Manipal H.O (‑419550), date : 27.07.2026, Manipal H.O (‑293726), date : 30.07.2026, Manipal H.O (…) |
| 8446015800 | BO New Account Opening Wallet | 1,200 | date : 31.07.2026, Karje B.O (1200) |
| 8661006300 | NEFT outward payable pool account | −13,40,000 | date : 30.07.2026, Manipal H.O (‑94000), Barkur S.O (‑40000) |
| 8001002700 | Sukanya Samriddhi Account‑Receipts | −6,050 | TE SSA DF (‑6550), date : 31.07.2026, Karje B.O (500) |
| 8001000300 | Post Office Recurring Deposits ‑Receipts | 18,000 | date : 31.07.2026, Karje B.O (1500), Santhekattekalathur B.O (16500) |
| 8001000200 | Post Office Savings Bank Account ‑Payments | 34,267 | date : 31.07.2026, Karje B.O (2000), Santhekattekalathur B.O (32219), date : 22.07.2026, Saligrama S.O (48) |

Notable manual step (~26:00–28:00): the user copied the DATEWISE_DATA tables for **SSA Default Fee** and **Sukanya Samriddhi Receipts** into a scratch workbook (Book2, Excel 2007) side by side to prove the +6,550 / −6,550 offset is a mis‑posting between the two heads → to be corrected by a Transfer Entry (TE). Windows Calculator was also used to add office amounts (e.g. 2000 + 32219 ≈ 34,267).

### Phase L — Annexure‑IV monthly report (50:00–58:00, 11:31–11:35)
26. `Annexure‑IV TABLE‑1` → userform **"CBS Monthly Reconciliation Report to PAO by HO (Table 1)"**: Select Month (Jul‑2026 dropdown), DDO CODE (102603), HO NAME (Manipal H.O), Division (Udupi) — pre‑filled from office settings. Section *Approved Transfer Entry Details*: From (A/C dropdown), To (A/C dropdown), Amount, `ADD TE`, `View/Modify`, `GENERATE`.
27. TE added: From 8001002700 Sukanya Samriddhi Account‑Receipts → To 8008005900 SSA Default Fee, Amount 6550. `View/Modify` opens the TE list sheet (MONTH Jul‑26 | AC_CODE | AC_DESC | FROM(‑)/TO(+) = −6550 / +6550; `GO BACK`; "DO NOT DELETE THIS ROW" header note). Status bar "Process completed successfully!".
28. `GENERATE` → Save‑As dialog → `CBS‑MRR‑TABLE1‑Jul‑26.xlsx` in `manipal ho cbs\` → opens in Excel. Layout: title "CBS Monthly Reconciliation Report to PAO by the HO (Due Date: 4th of every month)", Table‑1, DDO Code, Month; columns SL NO | A/c Code | A/c Code Description | Finacle (Receipts, Payments) | Monthly Cash Account* (Receipts, Payments) | Difference (Finacle − Cash Account) (Receipts, Payments); TOTAL row (Finacle Rcpts 11,03,80,959 / Pmts 39,44,53,004.03; Cash 11,10,84,156 / 39,44,18,737.03; Diff −7,03,197 / 34,267). Footnote "* Monthly Cash Account = Sum of Daily Cash Books + Approved Transfer Entries of DDO"; signature block "SBCO in‑charge / Postmaster Manipal H.O"; "Forwarded to the General Manager(F) / DA(P)"; "Copy to: The S/SPOs, Udupi Division for information." Note the TE has already been applied (SSA Default Fee diff shows 0; Sukanya shows +500 residual).
29. `Annexure‑IV TABLE‑2` → userform "(Table 2)": same header; radio **Preparing for first Time / Preparing for subsequent months**; checkbox *no discrepancy*; `UPLOAD OLD DATA`, `GET TEMPLATE` (creates Book3 with headers AC_CODE | DESCRIPTION | RECEIPT_DIFF | PAYMENT_DIFF for prior‑month opening balances); button "Upload TABLE‑1 xlsx file for Jul‑2026"; *Approved Transfer Entry Details for older months* (From/To/Amount, `Add TE`, `View/Modify`); `GENERATE`. Dialog "successfully imported" after uploading Table‑1.
30. Output `CBS‑MRR‑TABLE2‑Jul‑26.xlsx`: "Detailed CBS Monthly Reconciliation Report to PAO by the HO", Table‑2, columns A/c Code Description | Opening Balance in the Difference Finacle‑Cash Account (R/P) | Current Month Difference (R/P) | Rectified During the Current Month (R/P) | Pending for Rectification (R/P); TOTAL −7,03,197 / 34,267; footer "(a) Reasons for pending for Rectification :", "(b) Date by which Pendency Cleared :".

**Not demonstrated:** `BACKUP`, `RESTORE`, `ABOUT`, `HELP`, `EXPORT`/`PRINT` on DESC.RPT, `BULK UPLOAD`, `DELETE ALL`/`DATE RANGE` deletes.

---

## 5. Dialogs / popups catalogue

| Trigger | Title / text |
|---|---|
| CBS upload done | *Complete* — "Batch Processing for CBS report is Complete! Total Files Selected / Successfully Processed / Failed‑Invalid / Processing Time / See 'Processing Summary' sheet" |
| Duplicate date | *Duplicate Found: UPLOAD RESTRICTED* — "Data already available for the Date: dd‑mm‑yyyy, Number of entries : N" |
| Office‑wise upload done | *Microsoft Excel* — "DATA process complete" |
| Wrong APT file | *Microsoft Excel* — "REPORT IS NOT BELONG TO A/C CODE : <code>" |
| TE added | status bar "Process completed successfully!" |
| Table‑1 uploaded into Table‑2 form | "successfully imported" |
| Date cells | *Select Date* month‑grid picker |
| Value cell click | *SELECT A/C CODE* — code dropdown, from/to dates, `DATEWISE SUMMERY`, `COMPARE WITH IT 2.0 TRANSACTION REPORT`, `COMPARE WITH IT 2.0 GL WISE REPORT` |
| Annexure buttons | *CBS Monthly Reconciliation Report to PAO by HO (Table 1 / Table 2)* userforms |

---

## 6. File / folder conventions used

```
manipal ho cbs\
├─ office settings.xlsx
├─ CBS-MRR-TABLE1-Jul-26.xlsx        (generated)
├─ CBS-MRR-TABLE2-Jul-26.xlsx        (generated)
├─ BACKUP\
└─ REPORTS\
   ├─ JULY26\
   │  ├─ FINACLE\
   │  │  ├─ GL IT2.0 Transaction GL Wise Report (Incl HO,SO &BOs) - Consolidated\   01 07 2026.xls …
   │  │  └─ GL IT2.0 Transaction Report - Consolidated(Previous Day)\JULY 2026\     02 07 2026.xls …
   │  ├─ CASHBOOK\   export (19).xls … export (45).xls
   │  └─ apt\        export(12).xls …
   └─ AUGUST 2026\
```
All portal downloads are Excel 97‑2003 `.xls` named `export(n).xls`; the user renames/moves them manually.

---

## 7. Observations, defects and improvement candidates

1. **Encoding bug:** description "RSAO–POSB IT TDS–Receipts" renders as `RSAOâ€"POSB IT TDSâ€"` — UTF‑8 bytes decoded as Windows‑1252 during `.xls` import.
2. **Typos in UI:** "DATEWISE SUMMERY", "Descrepancy Reports", "REPORT IS NOT BELONG TO A/C CODE".
3. **Macro trust:** first run needs a Trusted Location; consider a signed VBA project or an on‑open instruction sheet.
4. **Repetitive manual loop:** per account × per date × per office the user must download an APT report from the portal and upload it. Candidates: bulk APT upload per month, auto‑detect date from DATEWISE, auto‑fill remark text `date : dd.mm.yyyy, <Office> (<amount>)` from the office‑wise difference rows, and auto‑add TE when two heads offset exactly.
5. **Scratch work outside the tool:** offset detection (SSA DF vs Sukanya) and summing office amounts was done in a separate workbook / calculator — could be an "offset finder" feature and a total row on `compare.transaction.report`.
6. **Progress messages inconsistent:** "Processing file 4 of 5 (0 valid 3 invalid)" mid‑run vs final "4 selected / 4 processed / 0 failed".
7. **Sheet naming:** `TEMP.CBR` = cashbook, `TEMP.FIN` = Finacle, `TEMP.CLR` = office‑level CBS — abbreviations are easy to confuse; comment them in code.
8. **Full‑column SUMIFS over ~975 codes × three staging tables** → visible recalculation lag ("Saving…", "Calculating") on every filter; bounded ranges or a pre‑aggregated pivot would help.
9. **Filtered‑table drill‑down** relies on Excel autofilter state (status bar "1 of 975 records found"); `REMOVE FILTER` buttons exist because stale filters otherwise hide rows.
10. **Date handling:** UI dates are dd‑mm‑yyyy text in some captions and real dates in others; Table‑1 month is chosen from a dropdown, but the home date range must match it manually.
11. Office master must be maintained by the user (`office settings.xlsx`); template rows "MODEL OFFICE …" ship as placeholders and should be cleared by `RESET`.
