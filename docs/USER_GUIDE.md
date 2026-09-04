# User guide — SBCO Reconciliation

For SBCO staff at a Head Post Office. This walks through the daily and monthly
routine required by SB Order No. 09/2026, using this tool. No technical
background is assumed.

---

## 1. Getting the tool onto your PC

Download `SBCO-Reconciliation-<version>-windows-x64.zip`, extract it anywhere
you like (Desktop, Documents, a shared drive), open the folder and double-click
**SBCO Reconciliation** (the application file). The tool opens in your web
browser.

- You do **not** need administrator rights.
- You do **not** need Python or anything else installed.
- Nothing leaves your PC: the tool runs entirely offline and only your own
  browser can reach it.
- Keep the black window open while you work; close it when you are done.

**If Windows blocks something** — two different Windows features can react to
downloaded files, and they behave differently:

- *"Windows protected your PC"* (SmartScreen): choose **More info → Run
  anyway**, or clear the download mark first — right-click the downloaded
  `.zip` → Properties → tick **Unblock** → OK, then extract again.
- *"Smart App Control blocked a file that may be unsafe"*: this one has no
  run-anyway option. It blocks downloaded scripts (`.bat`) outright — which is
  exactly why the tool starts from the signed application file instead. If it
  ever blocks the application file itself, re-download the official release
  zip and verify it against `SHA256SUMS.txt`; the only override for a genuine
  Smart App Control block is turning it off in Windows Security (a permanent,
  one-way switch) — a last resort to discuss with your IT/divisional office.

Your data is stored in your Windows user profile
(`%LOCALAPPDATA%\SBCO`), **not** in the program folder. To upgrade to a new
version, delete the old folder and extract the new one — your loaded reports,
register and settings are untouched.

If something will not start, run the built-in check — it looks at the PC and
says, in plain words, what is wrong and how to fix it. In the folder, click
the address bar, type `cmd`, press Enter, then run:

```
"SBCO Reconciliation.exe" -m sbco_recon.cli doctor
```

(`sbco.bat doctor` does the same on PCs without Smart App Control.)

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
   - DOP IT 2.0 portal (`app.indiapost.gov.in`): *Accounts ▸ Cashbook ▸ Step 2
     View/Download Cashbook ▸ Download Excel*. The browser saves it as
     `export.xls`, `export(1).xls`, … — there is no need to rename it; the
     tool reads what is inside, not the file name.
2. **Drag both files onto Add reports.** The tool identifies each one itself,
   refuses duplicates, and tells you exactly why if a file is not recognised.
   A report for a date that is already loaded is refused too ("*already loaded
   for 01-07-2026 — upload #12*"): a re-downloaded copy carries a new run time
   and would otherwise count twice. Undo the earlier upload first if the new
   file should replace it.
3. **Read the Reconcile screen.** Set the period; the balance strip shows
   Finacle vs Cash Book and the net difference. *Breaks only* lists just the
   account codes that do not agree.
   - Heed the yellow warnings: if a day in the period has no report loaded,
     differences for that day are not reliable — load the missing file first.
4. **Investigate each break.** Double-click a row (or use the Investigate
   screen) to see *which day* the break began. To see *which office* it came
   from, load two more files for that day:
   - Finacle MIS: *GL IT 2.0 Transaction Report — Consolidated (Previous Day)*
     with the **Set ID** (the whole HO set), which lists every SOL as a
     "*NNNN - Office*" section;
   - DOP IT 2.0: *Treasury ▸ Reports ▸ Accounting Details Office Wise*, for the
     account code and the date (again saved as `export(n).xls`).

   The office-by-office pane then shows the HO, each SO and each BO with
   Finacle, APT and the difference. Offices are matched by office ID, or by
   name when the portal export leaves the ID blank ("Barkur S.O" and
   "Barkur SO" are the same office).
5. **Record it.** Press **Save to register** — every break in the period goes
   into the Discrepancy Register (Annexure-IV Table-3) with the next serial
   number, and the office column is filled in from the office-wise figures
   when they are loaded ("*Barkur SO (1,000)*"). Pressing it twice cannot
   double-enter anything. Then report the discrepancy to the Postmaster for
   rectification, as the SOP requires.

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
   to-code up. Say what each TE applies to:
   - **This month's cash account (Table-1)** — the TE corrects a posting made
     this month. The Monthly Cash Account column of Table-1 is, per the
     order's own footnote, daily cash books **plus** these TEs.
   - **An earlier month's pending difference (Table-2)** — the TE rectifies a
     difference that Table-2 has been carrying. It appears under *Rectified
     during the current month* and never touches Table-1.

   One TE is one or the other; counting it in both would cancel a difference
   twice.
2. Press **Generate Table-1** — Annexure-IV **Table-1** is written as an
   .xlsx in the order's exact layout, with your DDO/HO/Division details and
   the signature block, ready to print and sign jointly with the Postmaster.
3. Press **Generate Table-2** — the detailed return: for every account code,
   the *opening* difference brought forward, this month's difference, what
   was rectified, and what is still pending. Opening balances are last
   month's closing balances, carried forward automatically from whatever the
   tool holds — nothing has to be re-uploaded month after month.

   **Preparing Table-2 for the first time** (or after moving from the Excel
   tool): give the tool the balances it should open with. Press **Load
   opening balances…**, choose the month, and pick last month's Table-2 or
   a sheet with the columns `AC_CODE | DESCRIPTION | RECEIPT_DIFF |
   PAYMENT_DIFF`. From then on the carry-forward is automatic.
4. Export **Table-3** for the register (Register screen) and include the
   month's position of pending rectifications.

## 7. Files, mistakes and undo

The **Files** screen lists every upload. If a wrong file was loaded, **Undo
this upload** removes exactly that file's rows — nothing else. Uploading the
identical file twice is detected by content (even if renamed) and refused, and
so is a fresh download of a report whose dates and account codes are already
loaded.

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
sbco.bat annexure --month Jul-2026 --table 2 Annexure-IV Table-2
sbco.bat annexure --month Jul-2026 --table 2 --opening last-month-table2.xlsx
sbco.bat te --month Jul-2026                list the month's transfer entries
sbco.bat te --month Jul-2026 --add --from 8001000200 --to 8001000100 --amount 1000 --prior
sbco.bat doctor                             check the PC
```

On PCs where Smart App Control blocks `.bat` scripts, use the application
file's own command form instead — it is the same tool:

```
"SBCO Reconciliation.exe" -m sbco_recon.cli doctor
```

## 10. If something looks wrong

| What you see | What it means |
|---|---|
| "Windows protected your PC" (SmartScreen) | *More info → Run anyway*, or right-click the downloaded `.zip` → Properties → **Unblock** → OK and extract again. |
| "Smart App Control blocked a file" | No run-anyway exists. Start the tool from **SBCO Reconciliation** (the application file), never a `.bat`. If the application file itself is blocked, re-download and verify against `SHA256SUMS.txt`; disabling Smart App Control (permanent) is the last resort. |
| Yellow "No … report covers N day(s)" | A day in the period has no upload. Figures for those dates are not reliable — load the missing report. |
| "Account code … is not in the reference master" | The uploaded data uses a code the tool does not know. Verify it before putting it on a return. |
| A file is *rejected* | The message names the reason — wrong report, unreadable column, or a file that is not what its name says. Re-download in Excel format (never PDF). |
| A file is *duplicate* | That exact file (by content) is already loaded, or the dates and account codes it carries are. Use Files ▸ Undo first if you truly need to reload it. |
| A transfer entry "has nothing outstanding" | A Table-2 TE names a code with no pending difference. Check the from/to codes and whether the TE should have applied to Table-1 instead. |
