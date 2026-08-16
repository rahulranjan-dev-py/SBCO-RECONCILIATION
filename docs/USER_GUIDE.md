# User guide — SBCO Reconciliation

For SBCO staff at a Head Post Office. This walks through the daily and monthly
routine required by SB Order No. 09/2026, using this tool. No technical
background is assumed.

---

## 1. Getting the tool onto your PC

Download `SBCO-Reconciliation-<version>-windows-x64.zip`, extract it anywhere
you like (Desktop, Documents, a shared drive), open the folder and double-click
**SBCO Reconciliation.bat**. The tool opens in your web browser.

- You do **not** need administrator rights.
- You do **not** need Python or anything else installed.
- Nothing leaves your PC: the tool runs entirely offline and only your own
  browser can reach it.
- Keep the black window open while you work; close it when you are done.

Your data is stored in your Windows user profile
(`%LOCALAPPDATA%\SBCO`), **not** in the program folder. To upgrade to a new
version, delete the old folder and extract the new one — your loaded reports,
register and settings are untouched.

If something will not start, run `sbco.bat doctor` (in the same folder) — it
checks the PC and says, in plain words, what is wrong and how to fix it.

## 2. First-time setup (once)

1. Open **Settings** and enter your **DDO code**, **HO name** and **Division**.
   These are printed on the monthly return.
2. Prepare your **office list** as a spreadsheet with four columns —
   `OFFICE_NAME`, `OFFICE_ID`, `SOL_ID/BO_CODE`, `SOL_ID_GROUP` — one row per
   office under your HO (a starter template is in `data/` next to this guide).
   For HOs and SOs the SOL group is their own SOL ID; for BOs it is the parent
   SO's SOL ID, because Finacle posts BO transactions there.
3. Drag the office file onto **Add reports**. The tool recognises it
   automatically. Loading a corrected list later replaces the old one.

## 3. The daily routine

Per SOP paragraph 4, SBCO verifies the CBS figures in the HO Cash Book against
the consolidated Finacle report, account code by account code, every day.

1. **Download the two reports** for the previous day:
   - Finacle MIS: *GL IT 2.0 Transaction GL Wise Report (Incl HO, SO & BOs) —
     Consolidated (Previous Day)*, with the HO SOL ID — save as Excel, not PDF;
   - APT: *Accounts ▸ Accounts Consolidation ▸ Cashbook ▸ Download Cashbook (XLS)*.
2. **Drag both files onto Add reports.** The tool identifies each one itself,
   refuses duplicates, and tells you exactly why if a file is not recognised.
3. **Read the Reconcile screen.** Set the period; the balance strip shows
   Finacle vs Cash Book and the net difference. *Breaks only* lists just the
   account codes that do not agree.
   - Heed the yellow warnings: if a day in the period has no report loaded,
     differences for that day are not reliable — load the missing file first.
4. **Investigate each break.** Double-click a row (or use the Investigate
   screen) to see *which day* the break began. If you also load the APT
   *Accounting Details* report for that code (Treasury ▸ Reports ▸ Accounting
   Details, office: all), the office-by-office pane shows *which office* it
   came from.
5. **Record it.** Press **Save to register** — every break in the period goes
   into the Discrepancy Register (Annexure-IV Table-3) with the next serial
   number. Pressing it twice cannot double-enter anything. Then report the
   discrepancy to the Postmaster for rectification, as the SOP requires.

## 4. Settling a discrepancy

The order treats a discrepancy as settled only once the rectification is
verified. When the Postmaster's side has posted the correction:

1. Open **Register**, find the entry (the *Open* filter shows what is
   pending and for how many days).
2. Click **Settle…**, enter the date of rectification and the particulars —
   the Misc. transaction posted in APT, the transfer entry, or both.

Entries stay on the register permanently; serial numbers restart from 1 each
April, exactly as the order prescribes. **Export Table-3** writes the register
for the financial year in the order's own (a)–(o) layout, ready for the
inspecting authority.

## 5. Clearing accounts

The **Clearing** screen pairs each of the eight mismatch heads (CBS, PLI/RPLI,
IPPB, Other × Receipts/Payments) against its `_Cleared` counterpart.
*Outstanding* is what was flagged as a mismatch but never cleared — the SOP's
rule that mismatches must be accounted separately, never netted off, is why
these heads are tracked head by head.

## 6. The monthly routine (by the 4th)

1. Record the DDO's **approved transfer entries** for the month on the
   *Monthly return* screen. A TE posts both legs: the from-code down, the
   to-code up. The Monthly Cash Account column of the return is, per the
   order's own footnote, daily cash books **plus** these TEs.
2. Press **Generate the return** — Annexure-IV **Table-1** is written as an
   .xlsx in the order's exact layout, with your DDO/HO/Division details and
   the signature block, ready to print and sign jointly with the Postmaster.
3. Export **Table-3** for the register (Register screen) and include the
   month's position of pending rectifications.

## 7. Files, mistakes and undo

The **Files** screen lists every upload. If a wrong file was loaded, **Undo
this upload** removes exactly that file's rows — nothing else. Uploading the
identical file twice is detected by content (even if renamed) and refused.

## 8. Where your data lives, and backups

Everything sits in one file: `%LOCALAPPDATA%\SBCO\sbco_recon.db`. To back up,
copy that file somewhere safe (do it with the tool closed). Generated returns
and exports go to the `reports` folder next to it — the path is shown at the
bottom-left of the tool.

## 9. Command line (optional)

Everything above is also a command, for scripted or scheduled runs:

```
sbco.bat load cashbook.xls finacle.xls      load reports
sbco.bat reconcile --month Jul-2026         the daily comparison
sbco.bat datewise 8001000200 --month Jul-2026
sbco.bat register --record --month Jul-2026
sbco.bat register --settle 4 --date 02-08-2026 --misc "Misc txn 12/2026"
sbco.bat annexure --month Jul-2026          Annexure-IV Table-1
sbco.bat doctor                             check the PC
```

## 10. If something looks wrong

| What you see | What it means |
|---|---|
| Yellow "No … report covers N day(s)" | A day in the period has no upload. Figures for those dates are not reliable — load the missing report. |
| "Account code … is not in the reference master" | The uploaded data uses a code the tool does not know. Verify it before putting it on a return. |
| A file is *rejected* | The message names the reason — wrong report, unreadable column, or a file that is not what its name says. Re-download in Excel format (never PDF). |
| A file is *duplicate* | That exact file (by content) is already loaded. Use Files ▸ Undo first if you truly need to reload it. |
