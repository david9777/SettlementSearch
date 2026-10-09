/* ===== Settlement Tape — Privacy Wiretap Comps tab =====
   A researched (not scraped) table of class settlements pleading CIPA § 631 / § 632,
   the federal Wiretap Act (ECPA) or Florida's FSCA. Data lives in privacy_comps.js
   (generated from privacy_comps.json by build_privacy_comps.py), separate from the
   auto-refreshed tape so the 6-hourly bot never touches it. */
(function () {
  "use strict";

  var SRC = window.PRIVACY_COMPS || { rows: [], screened_out: [] };

  var STATUTES = [
    { key: "cipa_631", label: "§ 631", long: "CIPA § 631 (wiretapping)" },
    { key: "cipa_632", label: "§ 632", long: "CIPA § 632 (eavesdropping / recording)" },
    { key: "cipa_632_7", label: "§ 632.7", long: "CIPA § 632.7 (cellular call recording)" },
    { key: "ecpa_wiretap", label: "ECPA", long: "Federal Wiretap Act / ECPA (18 U.S.C. § 2511)" },
    { key: "fsca", label: "FSCA", long: "Florida Security of Communications Act (Fla. Stat. § 934.10)" },
  ];
  var PEN = { key: "cipa_638_51", label: "§ 638.51", long: "CIPA § 638.51 (pen register / trap-and-trace)" };

  var ROWS = (SRC.rows || []).map(prep);

  var state = {
    q: "",
    statutes: new Set(),  // OR: show rows pleading any selected statute
    pen: "any",           // "any" | "pled" | "not"
    status: "",
    sortKey: "key_date",
    sortDir: "desc",
  };

  // ---------- Helpers ----------
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function stripNum(x) { return parseFloat(x.toFixed(2)).toString(); }
  function compact(n) {
    if (n == null || isNaN(n)) return null;
    var abs = Math.abs(n);
    if (abs >= 1e9) return stripNum(n / 1e9) + "B";
    if (abs >= 1e6) return stripNum(n / 1e6) + "M";
    if (abs >= 1e3) return stripNum(n / 1e3) + "K";
    return stripNum(n);
  }
  function money(n) { var c = compact(n); return c == null ? null : "$" + c; }
  function perMember(n) {
    if (n == null || isNaN(n)) return null;
    return n < 10 ? "$" + n.toFixed(2) : money(n);
  }
  function fullNum(n) { return n == null ? null : Number(n).toLocaleString("en-US"); }
  function pled(r, k) { return r[k] === "pled"; }

  function prep(r) {
    r.per_member = (r.fund_amount && r.class_size) ? r.fund_amount / r.class_size : null;
    if (r.final_approval_date) { r.key_date = r.final_approval_date; r.key_label = "Final"; }
    else if (r.prelim_approval_date) { r.key_date = r.prelim_approval_date; r.key_label = "Prelim"; }
    else if (r.motion_prelim_filed) { r.key_date = r.motion_prelim_filed; r.key_label = "Motion"; }
    else { r.key_date = null; r.key_label = ""; }
    return r;
  }
  function statusClass(s) {
    var k = (s || "").toLowerCase();
    if (k.indexOf("final") >= 0) return "status-final";
    if (k.indexOf("motion") >= 0) return "status-pending";
    if (k.indexOf("prelim") >= 0) return "status-preliminary";
    return "status-pending";
  }
  function pills(r, withPen) {
    var out = STATUTES.filter(function (s) { return pled(r, s.key); }).map(function (s) {
      return '<span class="stat-pill" title="' + esc(s.long) + '">' + esc(s.label) + "</span>";
    });
    if (withPen && pled(r, PEN.key)) {
      out.push('<span class="stat-pill stat-pill-pen" title="' + esc(PEN.long) + ' also pled">' + esc(PEN.label) + "</span>");
    }
    return out.join("");
  }

  // ---------- Filtering & sorting ----------
  function matches(r) {
    if (state.statutes.size) {
      var any = false;
      state.statutes.forEach(function (k) { if (pled(r, k)) any = true; });
      if (!any) return false;
    }
    if (state.pen === "pled" && !pled(r, PEN.key)) return false;
    if (state.pen === "not" && pled(r, PEN.key)) return false;
    if (state.status && r.status !== state.status) return false;
    if (state.q) {
      var hay = [r.short_name, r.caption, r.defendant, r.court, r.docket, r.judge, r.industry,
        r.technology, r.other_claims, r.plaintiff_counsel, r.class_definition]
        .filter(Boolean).join(" ").toLowerCase();
      if (hay.indexOf(state.q.toLowerCase()) < 0) return false;
    }
    return true;
  }
  function view() {
    var dir = state.sortDir === "asc" ? 1 : -1, k = state.sortKey;
    return ROWS.filter(matches).sort(function (a, b) {
      var va = a[k], vb = b[k];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir;
    });
  }

  // ---------- Rendering ----------
  var el = {};
  function $(id) { return document.getElementById(id); }

  function renderTiles() {
    var tiles = [
      { id: "all", val: ROWS.length, label: "Settlements", sub: "clear filters →" },
    ].concat(STATUTES.filter(function (s) { return s.key !== "cipa_632_7"; }).map(function (s) {
      return { id: s.key, val: ROWS.filter(function (r) { return pled(r, s.key); }).length,
               label: s.label === "ECPA" ? "Federal Wiretap / ECPA" : s.label === "FSCA" ? "Florida FSCA" : "CIPA " + s.label,
               sub: "pled →" };
    })).concat([
      { id: "no-pen", val: ROWS.filter(function (r) { return !pled(r, PEN.key); }).length,
        label: "Without § 638.51", sub: "no pen-register count →" },
    ]);
    el.tiles.innerHTML = tiles.map(function (t) {
      var active = (t.id === "no-pen" && state.pen === "not") ||
        (t.id !== "all" && t.id !== "no-pen" && state.statutes.size === 1 && state.statutes.has(t.id));
      return '<button class="metric' + (active ? " active" : "") + '" data-tile="' + t.id + '">' +
        '<div class="metric-value">' + t.val + "</div>" +
        '<div class="metric-label">' + esc(t.label) + "</div>" +
        '<div class="metric-sub">' + esc(t.sub) + "</div></button>";
    }).join("");
  }

  function renderChips() {
    el.chips.innerHTML = STATUTES.map(function (s) {
      var on = state.statutes.has(s.key);
      return '<button type="button" class="chip' + (on ? " on" : "") + '" data-key="' + s.key +
        '" aria-pressed="' + on + '" title="' + esc(s.long) + '">' + esc(s.label) + "</button>";
    }).join("");
  }

  function render() {
    var rows = view();
    el.body.innerHTML = "";
    el.empty.hidden = rows.length > 0;
    var frag = document.createDocumentFragment();
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.tabIndex = 0;
      tr.setAttribute("role", "button");
      var site = r.settlement_website || (r.sources && r.sources[0] && r.sources[0].url);
      tr.innerHTML =
        '<td class="case-cell">' +
          '<div class="case-name">' + esc(r.short_name) + "</div>" +
          '<div class="case-def">' + esc(r.defendant || "") + "</div>" +
          '<div class="case-court">' + esc([r.court, r.docket].filter(Boolean).join(" · ")) + "</div>" +
        "</td>" +
        '<td class="claims-cell">' + pills(r, true) + "</td>" +
        '<td class="num amount-cell">' + (money(r.fund_amount) ? esc(money(r.fund_amount)) : '<span class="amount-na">N/A</span>') + "</td>" +
        '<td class="num">' + (r.class_size != null ? esc(compact(r.class_size)) : "—") + "</td>" +
        '<td class="num">' + (perMember(r.per_member) ? esc(perMember(r.per_member)) : "—") + "</td>" +
        '<td class="terms-cell"><div class="clamp">' + esc(r.payment_terms || "—") + "</div></td>" +
        '<td class="terms-cell"><div class="clamp">' + esc(r.fees_requested || "—") + "</div></td>" +
        '<td><span class="status ' + statusClass(r.status) + '">' + esc(r.status) + "</span>" +
          (r.key_date ? '<div class="key-date">' + esc(r.key_label) + " " + esc(r.key_date) + "</div>" : "") + "</td>" +
        '<td class="terms-cell"><div class="clamp">' + esc(r.technology || "—") + "</div>" +
          (r.industry ? '<div class="case-def">' + esc(r.industry) + "</div>" : "") + "</td>" +
        '<td class="source-cell">' + (site
          ? '<a href="' + esc(site) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()">' +
            (r.settlement_website ? "Settlement site" : "Source") + " ↗</a>"
          : "—") + "</td>";
      tr.addEventListener("click", function () { openDetail(r); });
      tr.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(r); }
      });
      frag.appendChild(tr);
    });
    el.body.appendChild(frag);
    el.count.innerHTML = "Showing <strong>" + rows.length + "</strong> of " + ROWS.length + " settlements";
    el.table.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.classList.remove("sorted", "asc", "desc");
      if (th.dataset.sort === state.sortKey) th.classList.add("sorted", state.sortDir);
    });
    renderTiles();
    renderChips();
    el.pen.value = state.pen;
    el.status.value = state.status;
  }

  function renderScreened() {
    var list = SRC.screened_out || [];
    if (!list.length) { el.screened.hidden = true; return; }
    el.screenedCount.textContent = list.length;
    el.screenedList.innerHTML = list.map(function (s) {
      return "<li><strong>" + esc(s.name) + "</strong> — " + esc(s.reason) + "</li>";
    }).join("");
  }

  // ---------- Detail drawer (shares the tape's drawer; app.js owns closing) ----------
  function row(k, v, mono) {
    if (v == null || v === "") return "";
    return '<div class="detail-row"><div class="k">' + esc(k) + '</div><div class="v' + (mono ? " mono" : "") + '">' + esc(v) + "</div></div>";
  }
  function htmlRow(k, html) {
    return html ? '<div class="detail-row"><div class="k">' + esc(k) + '</div><div class="v">' + html + "</div></div>" : "";
  }
  function statuteList(r) {
    return STATUTES.concat([PEN]).map(function (s) {
      var v = r[s.key] || "unknown";
      var cls = v === "pled" ? "yes" : v === "not_pled" ? "no" : "unk";
      return '<div class="statute-line"><span class="statute-mark ' + cls + '">' +
        (v === "pled" ? "✓" : v === "not_pled" ? "–" : "?") + "</span>" + esc(s.long) +
        ' <span class="statute-val">' + esc(v.replace("_", " ")) + "</span></div>";
    }).join("");
  }
  function openDetail(r) {
    var detail = $("detail"), overlay = $("overlay"), bodyEl = $("detailBody");
    var sources = (r.sources || []).map(function (s) {
      return '<a class="doc-link" href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.label || s.url) + " ↗</a>";
    }).join("");
    bodyEl.innerHTML =
      '<div class="detail-eyebrow">Privacy wiretap settlement · ' + esc(r.status) + "</div>" +
      '<h2 class="detail-title">' + esc(r.short_name) + "</h2>" +
      '<p class="detail-def">' + esc(r.caption || r.defendant || "") + "</p>" +
      '<div class="detail-hero">' +
        '<div><div class="h-val">' + (money(r.fund_amount) || "N/A") + '</div><div class="h-lbl">Fund</div></div>' +
        '<div><div class="h-val">' + (r.class_size != null ? compact(r.class_size) : "—") + '</div><div class="h-lbl">Class size</div></div>' +
        '<div><div class="h-val">' + (perMember(r.per_member) || "—") + '</div><div class="h-lbl">Gross per member</div></div>' +
      "</div>" +
      '<div class="statute-block">' + statuteList(r) + "</div>" +
      '<div class="detail-grid">' +
        row("Court", r.court) + row("Docket", r.docket, true) + row("Judge", r.judge) +
        row("Status", r.status) +
        row("Prelim motion filed", r.motion_prelim_filed, true) +
        row("Prelim approval", r.prelim_approval_date, true) +
        row("Final hearing", r.final_hearing_date, true) +
        row("Final approval", r.final_approval_date, true) +
        row("Why it's in window", r.window_basis) +
        row("Class", r.class_definition) +
        row("Class size", r.class_size != null ? fullNum(r.class_size) + (r.class_size_note ? " (" + r.class_size_note + ")" : "") : r.class_size_note) +
        row("Fund", r.fund_amount != null ? "$" + fullNum(r.fund_amount) : null) +
        row("Structure", r.settlement_structure) +
        row("Payment terms", r.payment_terms) +
        row("Attorneys' fees", r.fees_requested) +
        row("Service awards", r.service_award) +
        row("Injunctive relief", r.injunctive_relief) +
        row("Other claims", r.other_claims) +
        row("Technology", r.technology) + row("Industry", r.industry) +
        row("Plaintiff counsel", r.plaintiff_counsel) +
        htmlRow("Settlement site", r.settlement_website
          ? '<a class="official-link" href="' + esc(r.settlement_website) + '" target="_blank" rel="noopener">Open settlement website ↗</a>' : "") +
        row("Claims evidence", r.statute_evidence) +
        htmlRow("Sources", sources ? '<div class="doc-list">' + sources + "</div>" : "") +
        row("Cross-check", "Claims: " + (r.xcheck_claims || "—") + " · Timing/money: " + (r.xcheck_timing || "—") +
          " · Confidence: " + (r.confidence || "—")) +
        row("Cross-check notes", r.xcheck_notes) +
        row("Open questions", r.open_questions) +
      "</div>";
    detail.hidden = false;
    overlay.hidden = false;
    $("detailClose").focus();
  }

  // ---------- CSV ----------
  function csvCell(v) {
    if (v == null) return "";
    var s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function exportCSV() {
    var rows = view();
    var cols = [
      ["short_name", "Case"], ["caption", "Caption"], ["defendant", "Defendant"],
      ["court", "Court"], ["docket", "Docket"], ["judge", "Judge"],
      ["cipa_631", "CIPA 631"], ["cipa_632", "CIPA 632"], ["cipa_632_7", "CIPA 632.7"],
      ["ecpa_wiretap", "Federal Wiretap/ECPA"], ["fsca", "Florida FSCA"], ["cipa_638_51", "CIPA 638.51"],
      ["other_claims", "Other Claims"], ["fund_amount", "Fund (USD)"], ["class_size", "Class Size"],
      ["class_size_note", "Class Size Note"], ["per_member", "Gross Per Member (USD)"],
      ["settlement_structure", "Structure"], ["payment_terms", "Payment Terms"],
      ["fees_requested", "Attorneys' Fees"], ["service_award", "Service Awards"],
      ["injunctive_relief", "Injunctive Relief"], ["status", "Status"],
      ["motion_prelim_filed", "Prelim Motion Filed"], ["prelim_approval_date", "Prelim Approval"],
      ["final_hearing_date", "Final Hearing"], ["final_approval_date", "Final Approval"],
      ["class_definition", "Class Definition"], ["technology", "Technology"], ["industry", "Industry"],
      ["plaintiff_counsel", "Plaintiff Counsel"], ["settlement_website", "Settlement Website"],
      ["statute_evidence", "Claims Evidence"], ["confidence", "Confidence"],
      ["xcheck_claims", "Claims Cross-check"], ["xcheck_timing", "Timing Cross-check"],
    ];
    var lines = [
      csvCell("Privacy wiretap settlements (CIPA 631/632, federal Wiretap Act/ECPA, Florida FSCA). " +
        "Researched " + (SRC.as_of || "") + "; window " + (SRC.window_start || "") + " to " + (SRC.window_end || "") +
        ". Not attorney-reviewed: confirm against the docket before citing."),
      cols.map(function (c) { return csvCell(c[1]); }).join(",") + ",Sources",
    ];
    rows.forEach(function (r) {
      lines.push(cols.map(function (c) {
        var v = r[c[0]];
        if (c[0] === "per_member" && v != null) v = v.toFixed(2);
        return csvCell(v);
      }).join(",") + "," + csvCell((r.sources || []).map(function (s) { return s.url; }).join(" ")));
    });
    var blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "privacy-wiretap-settlements-" + (SRC.as_of || "export") + ".csv";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ---------- Tabs ----------
  function showView(name) {
    var comps = name === "comps";
    $("view-tape").hidden = comps;
    $("view-comps").hidden = !comps;
    document.body.classList.toggle("view-comps", comps);
    document.querySelectorAll(".view-tab").forEach(function (b) {
      var on = b.dataset.view === name;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", String(on));
    });
    var hash = comps ? "#privacy-comps" : "";
    if (location.hash !== hash) history.replaceState(null, "", location.pathname + location.search + hash);
  }

  // ---------- Init ----------
  function init() {
    el = {
      tiles: $("compsTiles"), chips: $("compsChips"), body: $("compsBody"), empty: $("compsEmpty"),
      count: $("compsCount"), table: document.querySelector(".comps-table"), search: $("compsSearch"),
      pen: $("compsPen"), status: $("compsStatus"), screened: $("compsScreened"),
      screenedCount: $("compsScreenedCount"), screenedList: $("compsScreenedList"),
    };
    if (!el.body) return;
    $("compsAsOf").textContent = SRC.as_of || "—";
    $("compsWindow").textContent = (SRC.window_start || "?") + " to " + (SRC.window_end || "?");
    $("compsTabCount").textContent = ROWS.length || "";

    document.querySelectorAll(".view-tab").forEach(function (b) {
      b.addEventListener("click", function () { showView(b.dataset.view); });
    });
    el.chips.addEventListener("click", function (e) {
      var b = e.target.closest(".chip");
      if (!b) return;
      var k = b.dataset.key;
      if (state.statutes.has(k)) state.statutes.delete(k); else state.statutes.add(k);
      render();
    });
    el.tiles.addEventListener("click", function (e) {
      var b = e.target.closest(".metric");
      if (!b) return;
      var t = b.dataset.tile;
      if (t === "all") { state.statutes.clear(); state.pen = "any"; state.status = ""; state.q = ""; el.search.value = ""; }
      else if (t === "no-pen") { state.pen = state.pen === "not" ? "any" : "not"; }
      else {
        var only = state.statutes.size === 1 && state.statutes.has(t);
        state.statutes.clear();
        if (!only) state.statutes.add(t);
      }
      render();
    });
    var timer;
    el.search.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () { state.q = el.search.value.trim(); render(); }, 120);
    });
    el.pen.addEventListener("change", function () { state.pen = el.pen.value; render(); });
    el.status.addEventListener("change", function () { state.status = el.status.value; render(); });
    $("compsExport").addEventListener("click", exportCSV);
    el.table.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.addEventListener("click", function () {
        var k = th.dataset.sort;
        if (state.sortKey === k) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
        else { state.sortKey = k; state.sortDir = k === "short_name" ? "asc" : "desc"; }
        render();
      });
    });

    renderScreened();
    render();
    if (location.hash === "#privacy-comps") showView("comps");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
