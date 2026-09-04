/* Cashbook & CBS Reconciliation — interface logic.
   Plain ES modules-free JavaScript: no build step, no CDN, works offline. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  period: null,
  recon: null,
  filter: "breaks",
  find: "",
  config: {},
  offices: [],
  batches: [],
};

/* ── formatting ─────────────────────────────────────────────── */

const nf = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});

// QA-22: "—" now means "nothing loaded". A posted zero prints as 0.00.
const money = (n, present = true) => (n === 0 && !present ? "—" : nf.format(n));
const moneyAlways = (n) => nf.format(n);

function pad(n) { return String(n).padStart(2, "0"); }
function toDMY(d) { return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}`; }

function parseDMY(text) {
  const m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/.exec((text || "").trim());
  if (!m) return null;
  const day = +m[1], month = +m[2], year = +m[3];
  const d = new Date(year, month - 1, day);
  // JavaScript rolls impossible dates forward: 31-02-2026 became 03-03-2026
  // and 99-99-2026 became June 2034, silently reconciling a period nobody
  // asked for. Round-trip the parts to reject them (QA-05).
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) {
    return null;
  }
  return d;
}

function fmtISO(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}-${m}-${y}`;
}

/* ── talking to the local server ────────────────────────────── */

async function get(path, params = {}) {
  const q = new URLSearchParams(params).toString();
  const res = await fetch(`/api/${path}${q ? "?" + q : ""}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

async function post(path, payload) {
  const res = await fetch(`/api/${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-SBCO-Token": window.SBCO_TOKEN,
    },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

let toastTimer;
function toast(message, bad = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("bad", bad);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), bad ? 6500 : 3600);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ── period ─────────────────────────────────────────────────── */

function currentPeriod(explain = false) {
  const s = parseDMY($("#pStart").value);
  const e = parseDMY($("#pEnd").value);
  const say = (m) => { if (explain) toast(m, true); return null; };

  if (!s) return say("The start date is not a real date. Use dd-mm-yyyy.");
  if (!e) return say("The end date is not a real date. Use dd-mm-yyyy.");
  if (s > e) return say("The start date is after the end date.");
  const days = Math.round((e - s) / 86400000) + 1;
  if (days > 400) {
    return say(`That period covers ${days.toLocaleString("en-IN")} days. ` +
               "Reconcile at most 400 days at a time.");
  }
  return { start: toDMY(s), end: toDMY(e) };
}

function setPeriod(start, end) {
  $("#pStart").value = toDMY(start);
  $("#pEnd").value = toDMY(end);
}

function applyQuick(kind) {
  const now = new Date();
  if (kind === "this-month") {
    setPeriod(new Date(now.getFullYear(), now.getMonth(), 1),
              new Date(now.getFullYear(), now.getMonth() + 1, 0));
  } else if (kind === "last-month") {
    setPeriod(new Date(now.getFullYear(), now.getMonth() - 1, 1),
              new Date(now.getFullYear(), now.getMonth(), 0));
  } else if (kind === "this-quarter") {
    // Financial year starts in April. Counting months from April and letting
    // the Date constructor roll 12-14 into the next calendar year keeps Q4
    // (Jan-Mar) in the right year - it used to land a year early (QA-12).
    const fyStart = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
    const q = Math.floor(((now.getMonth() + 9) % 12) / 3);
    const start = new Date(fyStart, 3 + q * 3, 1);
    setPeriod(start, new Date(fyStart, 3 + q * 3 + 3, 0));
  }
}

/* ── the reconciliation view ────────────────────────────────── */

async function loadRecon() {
  const period = currentPeriod(true);
  if (!period) return;
  state.period = period;
  try {
    state.recon = await get("reconcile", { ...period, all: "1" });
    renderBalance();
    renderAlerts();
    renderLedger();
    $("#qtrTag").textContent = state.recon.period.quarter;
  } catch (err) {
    toast(err.message, true);
  }
}

function renderBalance() {
  const t = state.recon.totals;
  const box = $("#balance");
  $("#balF").textContent = moneyAlways(t.finacle);
  $("#balC").textContent = moneyAlways(t.cashbook);

  const broken = t.breaks > 0;
  box.classList.toggle("is-broken", broken);
  box.classList.toggle("is-clear", !broken);

  if (broken) {
    $("#balLbl").textContent = "Net difference";
    $("#balD").textContent = moneyAlways(t.difference);
    $("#balNote").textContent =
      `${t.breaks} account ${t.breaks === 1 ? "code does" : "codes do"} not agree`;
  } else {
    $("#balLbl").textContent = "Status";
    $("#balD").textContent = "In balance";
    $("#balNote").textContent = t.codes
      ? "Every account code with activity agrees"
      : "Nothing loaded for this period yet";
  }
}

function renderAlerts() {
  const cov = state.recon.coverage;
  const out = [];

  const gap = (label, days, count) => {
    if (!count) return;
    const shown = days.slice(0, 8).map(fmtISO).join("   ");
    const more = count > days.slice(0, 8).length
      ? `  and ${count - Math.min(8, days.length)} more` : "";
    out.push(`<div class="alert"><div><b>No ${label} loaded for
      ${count} day${count === 1 ? "" : "s"} in this period.</b>
      Differences on these dates are not reliable until you add the missing report.
      <span class="alert-days">${shown}${more}</span></div></div>`);
  };
  gap("Finacle / CBS data", cov.missing_finacle, cov.missing_finacle_count);
  gap("Cash Book data", cov.missing_cashbook, cov.missing_cashbook_count);

  state.recon.warnings
    .filter((w) => !w.includes("not reliable"))
    .forEach((w) => out.push(`<div class="alert"><div>${esc(w)}</div></div>`));

  $("#alerts").innerHTML = out.join("");
}

function renderLedger() {
  const all = state.recon.rows;
  const needle = state.find.trim().toLowerCase();

  let rows = state.filter === "breaks" ? all.filter((r) => !r.matched) : all;
  if (needle) {
    rows = rows.filter((r) =>
      r.code.includes(needle) || r.description.toLowerCase().includes(needle));
  }

  const head = `<div class="lrow lhead">
      <div>A/c code</div><div>Description</div>
      <div class="num">Finacle / CBS</div>
      <div class="gut-h" title="How far the cash book sits from Finacle"></div>
      <div class="num">Cash Book</div>
      <div class="num">Difference</div>
    </div>`;

  if (!rows.length) {
    const clear = state.filter === "breaks" && !needle && all.length;
    $("#ledger").innerHTML = head + `<div class="ledger-empty">
        ${clear
          ? `<div class="big">Nothing to reconcile</div>
             <p class="empty">Finacle and the cash book agree on every account
             code with activity in this period.</p>`
          : `<p class="empty">No rows match. ${needle
               ? "Try a different search."
               : "Add your reports for this period."}</p>`}
      </div>`;
    return;
  }

  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.difference)), 1);
  const denom = Math.log10(1 + maxAbs);

  const body = rows.map((r) => {
    const d = r.difference;
    const mag = Math.abs(d);
    const off = mag === 0 ? 0
      : Math.sign(d) * Math.min(1, Math.log10(1 + mag) / denom) * 44;
    return `<div class="lrow ${r.matched ? "agrees" : "broken"}">
      <div class="code">${esc(r.code)}</div>
      <div class="desc" title="${esc(r.description)}">${esc(r.description)}</div>
      <div class="num f">${money(r.finacle, r.finacle !== 0 || r.cashbook === 0)}</div>
      <div class="gut"><i style="left:calc(50% + ${off.toFixed(1)}px)"></i></div>
      <div class="num c">${money(r.cashbook)}</div>
      <div class="num d">${d === 0 ? "—" : moneyAlways(d)}</div>
    </div>`;
  }).join("");

  const sum = (key) => rows.reduce((acc, r) => acc + r[key], 0);
  const foot = `<div class="lrow lfoot">
      <div></div><div>${rows.length} of ${all.length} codes</div>
      <div class="num f">${moneyAlways(sum("finacle"))}</div>
      <div></div>
      <div class="num c">${moneyAlways(sum("cashbook"))}</div>
      <div class="num d">${moneyAlways(sum("difference"))}</div>
    </div>`;

  $("#ledger").innerHTML = head + `<div class="lbody">${body}</div>` + foot;

  $$(".lbody .lrow").forEach((row, i) => {
    row.addEventListener("dblclick", () => {
      const code = rows[i].code;
      $("#invCode").value = code;
      show("investigate");
      investigate();
    });
  });
}

/* ── investigate ────────────────────────────────────────────── */

async function investigate() {
  const code = $("#invCode").value.trim();
  const period = currentPeriod();
  if (!code) { toast("Enter an account code first.", true); return; }
  if (!period) { toast("Set a valid period at the top.", true); return; }

  try {
    const [dw, ow] = await Promise.all([
      get("datewise", { ...period, code, all: "0" }),
      get("officewise", { ...period, code }),
    ]);
    $("#invDesc").textContent = dw.description
      ? `${code} — ${dw.description}` : `${code} — not in the reference master`;

    $("#dwOut").innerHTML = dw.rows.length
      ? table(["Date", "Finacle", "Cash Book", "Difference"],
          dw.rows.map((r) => [
            { v: fmtISO(r.day), cls: "mono" },
            { v: money(r.finacle), cls: "num" },
            { v: money(r.cashbook), cls: "num" },
            { v: moneyAlways(r.difference), cls: "num " + (r.difference < 0 ? "neg" : "pos") },
          ]))
      : `<p class="empty">Every day in this period agrees for this code.</p>`;

    const warn = ow.warnings.length
      ? `<div class="alert"><div>${ow.warnings.map(esc).join("<br>")}</div></div>` : "";
    $("#owOut").innerHTML = warn + (ow.rows.length
      ? table(["Office", "Finacle", "APT", "Difference"],
          ow.rows.map((r) => [
            { v: esc(r.name) + (r.is_bo ? ' <span class="tag tag-bo">BO</span>' : "") },
            { v: money(r.finacle), cls: "num" },
            { v: money(r.apt), cls: "num" },
            { v: r.difference === 0 ? "—" : moneyAlways(r.difference),
              cls: "num " + (r.difference === 0 ? "zero" : "neg") },
          ]))
      : `<p class="empty">No office data for this code in this period.</p>`);
  } catch (err) {
    toast(err.message, true);
  }
}

function table(headers, rows) {
  const head = headers.map((h, i) =>
    `<th class="${i ? "num" : ""}">${esc(h)}</th>`).join("");
  const body = rows.map((cells) =>
    `<tr>${cells.map((c) => `<td class="${c.cls || ""}">${c.v}</td>`).join("")}</tr>`
  ).join("");
  return `<table class="tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

/* ── clearing ───────────────────────────────────────────────── */

async function loadClearing() {
  const period = currentPeriod();
  if (!period) return;
  try {
    const data = await get("clearing", period);
    $("#clrOut").innerHTML = `<div class="card">` + table(
      ["Category", "Side", "Mismatch a/c", "Flagged", "Cleared a/c", "Cleared", "Outstanding"],
      data.rows.map((r) => [
        { v: esc(r.category) },
        { v: esc(r.side) },
        { v: esc(r.mismatch_code), cls: "mono" },
        { v: money(r.mismatch), cls: "num" },
        { v: esc(r.cleared_code), cls: "mono" },
        { v: money(r.cleared), cls: "num" },
        { v: r.outstanding === 0 ? "—" : moneyAlways(r.outstanding),
          cls: "num " + (r.matched ? "zero" : "neg") },
      ])) + `</div>`;
  } catch (err) { toast(err.message, true); }
}

/* ── files ──────────────────────────────────────────────────── */

async function loadFiles() {
  const data = await get("state");
  state.batches = data.batches;
  if (!data.batches.length) {
    $("#filesOut").innerHTML =
      `<div class="card"><p class="empty">No reports loaded yet.
       Use <b>Add reports</b> at the top right to load your first file.</p></div>`;
    return;
  }
  $("#filesOut").innerHTML = `<div class="card">` + table(
    ["#", "Kind", "File", "Rows", "Covers", "Loaded", ""],
    data.batches.map((b) => [
      { v: b.id, cls: "mono" },
      { v: esc(b.source.replace(/_/g, " ")) },
      { v: esc(b.file_name) },
      { v: b.row_count.toLocaleString("en-IN"), cls: "num" },
      { v: b.period_start ? `${fmtISO(b.period_start)} – ${fmtISO(b.period_end)}` : "—",
        cls: "mono" },
      { v: esc((b.loaded_at || "").replace("T", " ")), cls: "mono" },
      { v: `<button class="link link-danger" data-reverse="${b.id}">Undo this upload</button>` },
    ])) + `</div>`;

  $$("[data-reverse]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.reverse;
      if (!confirm(`Undo upload #${id}? Only this file's rows are removed.`)) return;
      try {
        const res = await post("reverse", { batch_id: id });
        toast(`Upload #${id} undone — ${res.removed.toLocaleString("en-IN")} rows removed.`);
        await loadFiles();
        await loadRecon();
      } catch (err) { toast(err.message, true); }
    });
  });
}

/* ── settings ───────────────────────────────────────────────── */

function renderSettings() {
  $("#cfgDdo").value = state.config.ddo || "";
  $("#cfgHo").value = state.config.ho || "";
  $("#cfgDiv").value = state.config.division || "";

  $("#officesOut").innerHTML = state.offices.length
    ? table(["Office", "Office ID", "SOL ID / BO code", "Rolls up to"],
        state.offices.map((o) => [
          { v: esc(o.name) + (o.is_bo ? ' <span class="tag tag-bo">BO</span>' : "") },
          { v: esc(o.office_id), cls: "mono" },
          { v: esc(o.sol_id), cls: "mono" },
          { v: esc(o.sol_group), cls: "mono" },
        ]))
    : `<p class="empty">No office list loaded. Drop your office spreadsheet into
       <b>Add reports</b> — the tool recognises it automatically.</p>`;
}

/* ── monthly return ─────────────────────────────────────────── */

async function generateReturn() {
  const month = $("#anMonth").value.trim();
  if (!month) { toast("Enter the month, for example Jul-2026.", true); return; }
  $("#btnAnnex").disabled = true;
  $("#anHint").textContent = "Working…";
  try {
    const res = await post("annexure", {
      month, include_matched: $("#anAll").checked,
    });
    $("#anHint").innerHTML =
      `Saved as <b>${esc(res.file)}</b> — ${res.breaks} break${res.breaks === 1 ? "" : "s"}.
       <a href="/download?f=${encodeURIComponent(res.file)}">Open it</a>`;
    toast(`${res.file} saved to your working folder.`);
  } catch (err) {
    $("#anHint").textContent = "";
    toast(err.message, true);
  } finally {
    $("#btnAnnex").disabled = false;
  }
}

async function loadTransferEntries() {
  const month = $("#teMonth").value.trim();
  const data = await get("transfer-entries", month ? { month } : {});
  $("#teList").innerHTML = data.rows.length
    ? table(["Month", "From", "To", "Amount", "Applies to", "Remarks"],
        data.rows.map((r) => [
          { v: esc(r.month), cls: "mono" },
          { v: esc(r.from_code), cls: "mono" },
          { v: esc(r.to_code), cls: "mono" },
          { v: moneyAlways(Number(r.amount)), cls: "num" },
          { v: r.scope === "prior" ? "Earlier month (Table-2)" : "This month (Table-1)" },
          { v: esc(r.remarks) },
        ]))
    : `<p class="empty">No transfer entries recorded.</p>`;
}

async function generateReturn2() {
  const month = $("#anMonth").value.trim();
  if (!month) { toast("Enter the month, for example Jul-2026.", true); return; }
  $("#btnAnnex2").disabled = true;
  $("#an2Hint").textContent = "Working…";
  try {
    const res = await post("annexure2", { month, include_settled: $("#t2All").checked });
    const warn = res.warnings.length ? ` ${res.warnings.length} warning(s) are printed on the sheet.` : "";
    $("#an2Hint").innerHTML =
      `Saved as <b>${esc(res.file)}</b> — ${res.pending} pending, closing ${moneyAlways(res.closing)}.${warn}
       <a href="/download?f=${encodeURIComponent(res.file)}">Open it</a>`;
    toast(`${res.file} saved to your working folder.`);
  } catch (err) {
    $("#an2Hint").textContent = "";
    toast(err.message, true);
  } finally {
    $("#btnAnnex2").disabled = false;
  }
}

async function sendOpeningBalances(file) {
  const month = $("#anMonth").value.trim();
  if (!month) { toast("Enter the month these balances open, for example Jul-2026.", true); return; }
  try {
    const res = await fetch("/api/table2-opening", {
      method: "POST",
      headers: {
        "X-Filename": encodeURIComponent(file.name),
        "X-Month": encodeURIComponent(month),
        "X-SBCO-Token": window.SBCO_TOKEN,
      },
      body: file,
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    toast(`${data.rows} opening balance(s) recorded for ${data.month}.`);
  } catch (err) { toast(err.message, true); }
}

/* ── discrepancy register (Table-3) ─────────────────────────── */

const reg = { fy: "", filter: "open", rows: [], settling: null };

async function loadRegister() {
  try {
    const data = await get("register", reg.fy ? { fy: reg.fy } : {});
    reg.fy = data.fy;
    reg.rows = data.rows;
    $("#regFy").innerHTML = data.years
      .map((y) => `<option value="${esc(y)}" ${y === data.fy ? "selected" : ""}>FY ${esc(y)}</option>`)
      .join("");
    renderRegister();
  } catch (err) { toast(err.message, true); }
}

function renderRegister() {
  const rows = reg.rows.filter((r) =>
    reg.filter === "all" ? true : reg.filter === "open" ? !r.settled : r.settled);

  if (!rows.length) {
    const openCount = reg.rows.filter((r) => !r.settled).length;
    $("#regOut").innerHTML = `<div class="card"><p class="empty">${
      reg.rows.length === 0
        ? "The register is empty for this financial year. Use <b>Save to register</b> on the Reconcile screen to record a day's discrepancies."
        : reg.filter === "open"
          ? "Nothing is pending — every recorded discrepancy has been settled."
          : `No settled entries yet. ${openCount} still open.`}</p></div>`;
    return;
  }

  $("#regOut").innerHTML = `<div class="card">` + table(
    ["Sl", "Date", "A/c code", "Description", "Office",
     "Diff (Receipt)", "Diff (Payment)", "Status", ""],
    rows.map((r) => [
      { v: r.serial, cls: "mono" },
      { v: fmtISO(r.date), cls: "mono" },
      { v: esc(r.code), cls: "mono" },
      { v: esc(r.description) },
      { v: esc(r.office || "—") },
      { v: r.difference_receipt === 0 ? "—" : moneyAlways(r.difference_receipt),
        cls: "num " + (r.difference_receipt === 0 ? "zero" : "neg") },
      { v: r.difference_payment === 0 ? "—" : moneyAlways(r.difference_payment),
        cls: "num " + (r.difference_payment === 0 ? "zero" : "neg") },
      { v: r.settled
          ? `Settled ${fmtISO(r.rectified_date)}`
          : `Open · ${r.days_outstanding} day${r.days_outstanding === 1 ? "" : "s"}`,
        cls: r.settled ? "zero" : "" },
      { v: r.settled ? "" :
          `<button class="link" data-settle="${r.id}">Settle…</button>` },
    ])) + `</div>`;

  $$("[data-settle]").forEach((btn) =>
    btn.addEventListener("click", () => openSettle(+btn.dataset.settle)));
}

function openSettle(id) {
  const row = reg.rows.find((r) => r.id === id);
  if (!row) return;
  reg.settling = id;
  $("#settleTitle").textContent =
    `Settle Sl.${row.serial} — ${row.code} (${fmtISO(row.date)})`;
  $("#stDate").value = toDMY(new Date());
  $("#stMisc").value = "";
  $("#stTe").value = "";
  $("#settleCard").hidden = false;
  $("#settleCard").scrollIntoView({ behavior: "smooth", block: "center" });
}

async function settleEntry() {
  if (!reg.settling) return;
  const when = parseDMY($("#stDate").value);
  if (!when) { toast("Enter the rectification date as dd-mm-yyyy.", true); return; }
  const misc = $("#stMisc").value.trim();
  const te = $("#stTe").value.trim();
  if (!misc && !te) {
    toast("Record how it was rectified — the Misc. transaction, the transfer " +
          "entry, or both.", true);
    return;
  }
  try {
    await post("register-settle", {
      id: reg.settling, date: toDMY(when), misc, te,
    });
    $("#settleCard").hidden = true;
    reg.settling = null;
    toast("Settled and recorded in the register.");
    loadRegister();
  } catch (err) { toast(err.message, true); }
}

/* ── uploading ──────────────────────────────────────────────── */

function openSheet() {
  $("#veil").hidden = false;
  $("#results").innerHTML = "";
  $("#tally").textContent = "";
}

function closeSheet() { $("#veil").hidden = true; }

async function sendFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;

  const counts = { loaded: 0, duplicate: 0, rejected: 0, failed: 0 };
  $("#tally").textContent = `Reading ${files.length} file${files.length === 1 ? "" : "s"}…`;

  for (const file of files) {
    const row = document.createElement("div");
    row.className = "res";
    row.innerHTML = `<div class="res-code">…</div>
      <div><div class="res-name">${esc(file.name)}</div>
      <div class="res-why">Reading…</div></div><div class="res-rows"></div>`;
    $("#results").appendChild(row);

    try {
      const res = await fetch("/api/upload", {
        method: "POST",
        headers: {
          "X-Filename": encodeURIComponent(file.name),
          "X-SBCO-Token": window.SBCO_TOKEN,
        },
        body: file,
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);

      counts[data.status] = (counts[data.status] || 0) + 1;
      const code = { loaded: "OK", duplicate: "DUP", rejected: "REJ", failed: "ERR" }[data.status];
      const cls = { loaded: "res-ok", duplicate: "res-dup",
                    rejected: "res-rej", failed: "res-err" }[data.status];
      const why = data.status === "loaded"
        ? `Recognised as ${esc(data.reason.replace(/_/g, " "))}${data.detail ? " — " + esc(data.detail) : ""}`
        : `${esc(data.reason)}${data.detail ? " — " + esc(data.detail) : ""}`;

      row.querySelector(".res-code").className = `res-code ${cls}`;
      row.querySelector(".res-code").textContent = code;
      row.querySelector(".res-why").innerHTML = why;
      row.querySelector(".res-rows").textContent =
        data.rows ? `${data.rows.toLocaleString("en-IN")} rows` : "";
    } catch (err) {
      counts.failed++;
      row.querySelector(".res-code").className = "res-code res-err";
      row.querySelector(".res-code").textContent = "ERR";
      row.querySelector(".res-why").textContent = err.message;
    }
  }

  const done = counts.loaded + counts.duplicate + counts.rejected + counts.failed;
  $("#tally").innerHTML =
    `<b>${done} of ${files.length}</b> accounted for &nbsp;·&nbsp;
     ${counts.loaded} loaded, ${counts.duplicate} already had,
     ${counts.rejected} not recognised, ${counts.failed} failed`;

  await boot(false);
  await loadRecon();
}

/* ── navigation ─────────────────────────────────────────────── */

function show(view) {
  $$(".view").forEach((v) => v.classList.toggle("on", v.dataset.view === view));
  $$("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  $("#scroll").scrollTop = 0;

  if (view === "clearing") loadClearing();
  if (view === "register") loadRegister();
  if (view === "files") loadFiles();
  if (view === "settings") renderSettings();
  if (view === "return") {
    $("#anWho").textContent = state.config.ho
      ? `${state.config.ho} · DDO ${state.config.ddo} · ${state.config.division} Division`
      : "Not set — add your office details in Settings first";
    loadTransferEntries();
  }
}

/* ── start ──────────────────────────────────────────────────── */

async function boot(first = true) {
  const data = await get("state");
  state.config = data.config;
  state.offices = data.offices;
  state.batches = data.batches;

  $("#railOffice").textContent = data.config.ho || "No office set";
  $("#railFolder").textContent = data.folder;

  if (first) {
    $("#codeList").innerHTML = data.codes
      .map((c) => `<option value="${c.code}">${esc(c.description)}</option>`).join("");

    const latest = data.batches
      .map((b) => b.period_end).filter(Boolean).sort().pop();
    if (latest) {
      const [y, m] = latest.split("-").map(Number);
      setPeriod(new Date(y, m - 1, 1), new Date(y, m, 0));
      $("#anMonth").value = new Date(y, m - 1, 1)
        .toLocaleDateString("en-GB", { month: "short", year: "numeric" }).replace(" ", "-");
      $("#teMonth").value = $("#anMonth").value;
    } else {
      applyQuick("this-month");
    }
  }
}

function wire() {
  $$("#nav button").forEach((b) =>
    b.addEventListener("click", () => show(b.dataset.view)));

  $("#pQuick").addEventListener("change", (e) => {
    if (e.target.value) { applyQuick(e.target.value); e.target.value = ""; loadRecon(); }
  });
  ["#pStart", "#pEnd"].forEach((sel) => {
    $(sel).addEventListener("change", loadRecon);
    $(sel).addEventListener("keydown", (e) => { if (e.key === "Enter") loadRecon(); });
  });

  $$("#filterSeg button").forEach((b) =>
    b.addEventListener("click", () => {
      $$("#filterSeg button").forEach((o) => o.classList.toggle("on", o === b));
      state.filter = b.dataset.filter;
      renderLedger();
    }));

  let findTimer;
  $("#find").addEventListener("input", (e) => {
    clearTimeout(findTimer);
    findTimer = setTimeout(() => { state.find = e.target.value; renderLedger(); }, 140);
  });

  $("#btnAdd").addEventListener("click", openSheet);
  $("#sheetClose").addEventListener("click", closeSheet);
  $("#sheetDone").addEventListener("click", closeSheet);
  $("#veil").addEventListener("click", (e) => { if (e.target === $("#veil")) closeSheet(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#veil").hidden) closeSheet();
  });

  $("#btnBrowse").addEventListener("click", () => $("#filesIn").click());
  $("#filesIn").addEventListener("change", (e) => {
    sendFiles(e.target.files); e.target.value = "";
  });

  const drop = $("#drop");
  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault(); drop.classList.add("hot");
    }));
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault(); drop.classList.remove("hot");
    }));
  drop.addEventListener("drop", (e) => sendFiles(e.dataTransfer.files));

  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    if ($("#veil").hidden && e.dataTransfer.files.length) {
      openSheet(); sendFiles(e.dataTransfer.files);
    }
  });

  $("#btnInv").addEventListener("click", investigate);
  $("#invCode").addEventListener("keydown", (e) => {
    if (e.key === "Enter") investigate();
  });

  $("#btnCfg").addEventListener("click", async () => {
    try {
      const data = await post("config", {
        ddo: $("#cfgDdo").value, ho: $("#cfgHo").value, division: $("#cfgDiv").value,
      });
      state.config = data.config;
      $("#railOffice").textContent = data.config.ho || "No office set";
      $("#cfgHint").textContent = "Saved.";
      setTimeout(() => ($("#cfgHint").textContent = ""), 2500);
    } catch (err) { toast(err.message, true); }
  });

  $("#btnAnnex").addEventListener("click", generateReturn);
  $("#btnAnnex2").addEventListener("click", generateReturn2);
  $("#btnT2Seed").addEventListener("click", () => $("#t2SeedIn").click());
  $("#t2SeedIn").addEventListener("change", (e) => {
    if (e.target.files.length) sendOpeningBalances(e.target.files[0]);
    e.target.value = "";
  });
  $("#teMonth").addEventListener("change", loadTransferEntries);

  $("#btnTe").addEventListener("click", async () => {
    const payload = {
      month: $("#teMonth").value.trim(),
      from_code: $("#teFrom").value.trim(),
      to_code: $("#teTo").value.trim(),
      amount: $("#teAmt").value.trim(),
      scope: $("#teScope").value,
      remarks: $("#teNote").value.trim(),
    };
    if (!payload.month || !payload.from_code || !payload.to_code || !payload.amount) {
      toast("Month, both codes and the amount are all needed.", true); return;
    }
    try {
      await post("transfer-entry", payload);
      $("#teFrom").value = $("#teTo").value = $("#teAmt").value = $("#teNote").value = "";
      toast("Transfer entry added.");
      loadTransferEntries();
    } catch (err) { toast(err.message, true); }
  });

  $("#btnExport").addEventListener("click", async () => {
    if (!state.period) return;
    try {
      const res = await post("export", {
        ...state.period, kind: "reconcile", all: state.filter === "all",
      });
      toast(`${res.file} saved to your working folder.`);
      window.location = `/download?f=${encodeURIComponent(res.file)}`;
    } catch (err) { toast(err.message, true); }
  });

  $("#btnRecord").addEventListener("click", async () => {
    if (!state.period) return;
    try {
      const res = await post("record-discrepancies", { ...state.period });
      const skipped = res.skipped
        ? ` ${res.skipped} already on the register and skipped.` : "";
      toast(res.added
        ? `${res.added} entr${res.added === 1 ? "y" : "ies"} added to the FY ${res.fy} register.${skipped}`
        : `Nothing new to record.${skipped}`);
    } catch (err) { toast(err.message, true); }
  });

  $$("#regSeg button").forEach((b) =>
    b.addEventListener("click", () => {
      $$("#regSeg button").forEach((o) => o.classList.toggle("on", o === b));
      reg.filter = b.dataset.reg;
      renderRegister();
    }));
  $("#regFy").addEventListener("change", (e) => {
    reg.fy = e.target.value;
    loadRegister();
  });
  $("#btnRegExport").addEventListener("click", async () => {
    try {
      const res = await post("export", { kind: "table3", fy: reg.fy });
      toast(`${res.file} saved to your working folder.`);
      window.location = `/download?f=${encodeURIComponent(res.file)}`;
    } catch (err) { toast(err.message, true); }
  });
  $("#btnSettle").addEventListener("click", settleEntry);
  $("#btnSettleCancel").addEventListener("click", () => {
    $("#settleCard").hidden = true;
    reg.settling = null;
  });
}

wire();
boot().then(loadRecon).catch((err) => toast(err.message, true));
