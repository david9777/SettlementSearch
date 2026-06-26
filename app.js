/* ===== SettleSearch — application logic ===== */
(function () {
  "use strict";

  let DATA = [];

  // ---------- State ----------
  const state = {
    search: "",
    categories: new Set(),
    statuses: new Set(),
    rtypes: new Set(),
    yearMin: null,
    yearMax: null,
    amountMin: 0,       // 0 | numeric threshold | "has" | "none"
    showClosed: false,  // include settlements whose claim deadline has passed
    sortKey: "date_added",  // default: most recently added to the database first
    sortDir: "desc",
    renderCap: 500,     // rows rendered at once; grown by the "Show more" row
    online: false,      // true when the local data server is reachable
    lastUpdated: null,  // ISO timestamp of the last live refresh
  };
  const RENDER_CHUNK = 500;

  function setForKey(key) {
    if (key === "category") return state.categories;
    if (key === "record_type") return state.rtypes;
    return state.statuses;
  }

  // ---------- Element refs ----------
  const el = {
    search: document.getElementById("search"),
    filterCategory: document.getElementById("filter-category"),
    filterStatus: document.getElementById("filter-status"),
    filterRtype: document.getElementById("filter-rtype"),
    yearMin: document.getElementById("yearMin"),
    yearMax: document.getElementById("yearMax"),
    amountMin: document.getElementById("amountMin"),
    resetBtn: document.getElementById("resetBtn"),
    sortSelect: document.getElementById("sortSelect"),
    showClosed: document.getElementById("showClosed"),
    tableBody: document.getElementById("tableBody"),
    resultCount: document.getElementById("resultCount"),
    emptyState: document.getElementById("emptyState"),
    exportBtn: document.getElementById("exportBtn"),
    refreshBtn: document.getElementById("refreshBtn"),
    lastUpdated: document.getElementById("lastUpdated"),
    toast: document.getElementById("toast"),
    overlay: document.getElementById("overlay"),
    detail: document.getElementById("detail"),
    detailBody: document.getElementById("detailBody"),
    detailClose: document.getElementById("detailClose"),
    table: document.querySelector(".settlement-table"),
    metrics: {
      count: document.getElementById("m-count"),
      value: document.getElementById("m-value"),
      class: document.getElementById("m-class"),
      cats: document.getElementById("m-cats"),
      largest: document.getElementById("m-largest"),
    },
  };

  // ---------- Formatting helpers ----------
  function stripNum(x) {
    return parseFloat(x.toFixed(2)).toString();
  }
  function compact(n) {
    if (n == null || isNaN(n)) return null;
    const abs = Math.abs(n);
    if (abs >= 1e9) return stripNum(n / 1e9) + "B";
    if (abs >= 1e6) return stripNum(n / 1e6) + "M";
    if (abs >= 1e3) return stripNum(n / 1e3) + "K";
    return String(n);
  }
  function money(n) {
    const c = compact(n);
    return c == null ? null : "$" + c;
  }
  function fullNum(n) {
    return n == null ? "—" : n.toLocaleString("en-US");
  }
  function statusClass(s) {
    if (!s) return "status-pending";
    const k = s.toLowerCase();
    if (k.includes("final")) return "status-final";
    if (k.includes("global")) return "status-global";
    if (k.includes("prelim")) return "status-preliminary";
    if (k.includes("verdict")) return "status-verdict";
    return "status-pending";
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // ---------- Build filter UI ----------
  function uniqueSorted(key) {
    return Array.from(new Set(DATA.map((d) => d[key]).filter(Boolean))).sort();
  }
  function countFor(key, val) {
    return DATA.filter((d) => d[key] === val).length;
  }

  function buildCheckboxes(container, key, values) {
    const set = setForKey(key);
    container.innerHTML = "";
    values.forEach((val) => {
      const label = document.createElement("label");
      label.className = "check";
      label.innerHTML =
        '<input type="checkbox" value="' + esc(val) + '">' +
        "<span>" + esc(val) + "</span>" +
        '<span class="count">' + countFor(key, val) + "</span>";
      const input = label.querySelector("input");
      if (set.has(val)) input.checked = true; // preserve selection across rebuilds
      input.addEventListener("change", () => {
        if (input.checked) set.add(val);
        else set.delete(val);
        render();
      });
      container.appendChild(label);
    });
  }

  const RTYPE_ORDER = ["Settlement", "Announcement", "Lawsuit Filed", "Investigation", "Regulatory", "News & Guides"];
  function buildFilters() {
    const rtypes = uniqueSorted("record_type")
      .sort((a, b) => RTYPE_ORDER.indexOf(a) - RTYPE_ORDER.indexOf(b));
    buildCheckboxes(el.filterRtype, "record_type", rtypes);
    buildCheckboxes(el.filterCategory, "category", uniqueSorted("category"));
    buildCheckboxes(el.filterStatus, "status", uniqueSorted("status"));
    buildYearOptions();
  }

  function buildYearOptions() {
    const prevMin = el.yearMin.value, prevMax = el.yearMax.value;
    el.yearMin.innerHTML = "";
    el.yearMax.innerHTML = "";
    el.yearMin.add(new Option("From", ""));
    el.yearMax.add(new Option("To", ""));
    const years = DATA.map((d) => d.year).filter(Boolean);
    if (years.length) {
      const min = Math.min(...years), max = Math.max(...years);
      for (let y = max; y >= min; y--) {
        el.yearMin.add(new Option(y, y));
        el.yearMax.add(new Option(y, y));
      }
    }
    el.yearMin.value = prevMin || "";
    el.yearMax.value = prevMax || "";
  }

  // ---------- Filtering & sorting ----------
  // A settlement whose claim deadline has passed is "closed": kept in the data
  // and findable by search, but hidden from the default/newest view so it isn't
  // presented as a current opportunity.
  function todayISO() {
    var n = new Date();
    return n.getFullYear() + "-" + String(n.getMonth() + 1).padStart(2, "0") +
           "-" + String(n.getDate()).padStart(2, "0");
  }
  var TODAY = todayISO();
  function isExpired(d) {
    return !!d.claim_deadline && d.claim_deadline < TODAY;
  }

  function matches(d) {
    // Hide closed settlements unless the user opts in or is searching for one.
    if (isExpired(d) && !state.showClosed && !state.search) return false;
    if (state.categories.size && !state.categories.has(d.category)) return false;
    if (state.statuses.size && !state.statuses.has(d.status)) return false;
    if (state.rtypes.size && !state.rtypes.has(d.record_type || "Settlement")) return false;
    if (state.yearMin != null && (d.year == null || d.year < state.yearMin)) return false;
    if (state.yearMax != null && (d.year == null || d.year > state.yearMax)) return false;
    if (state.amountMin === "has") {
      if (d.amount == null) return false;
    } else if (state.amountMin === "none") {
      if (d.amount != null) return false;
    } else if (state.amountMin && (d.amount == null || d.amount < state.amountMin)) {
      return false;
    }
    if (state.search) {
      const q = state.search.toLowerCase();
      const hay = [
        d.case_name, d.short_name, d.defendant, d.category, d.record_type,
        d.court, d.court_full, d.judge, d.case_number, d.description,
        d.status, d.source,
      ].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }

  function sortRows(rows) {
    const { sortKey, sortDir } = state;
    const dir = sortDir === "asc" ? 1 : -1;
    return rows.slice().sort((a, b) => {
      let va = a[sortKey];
      let vb = b[sortKey];
      // Nulls always last regardless of direction
      const na = va == null, nb = vb == null;
      if (na && nb) return 0;
      if (na) return 1;
      if (nb) return -1;
      var cmp = (typeof va === "string") ? va.localeCompare(vb) * dir : (va - vb) * dir;
      // date_added is per-day, so break ties by amount (biggest of the day first).
      if (cmp === 0 && sortKey === "date_added") {
        return (b.amount || 0) - (a.amount || 0);
      }
      return cmp;
    });
  }

  function getView() {
    return sortRows(DATA.filter(matches));
  }

  // ---------- Rendering ----------
  // Newest date_added in the dataset — the "NEW" badge marks records from the
  // latest few batches the bot pulled, so it stays meaningful whenever you visit.
  var newestAdded = null;
  function computeNewestAdded() {
    newestAdded = null;
    for (var i = 0; i < DATA.length; i++) {
      var da = DATA[i].date_added;
      if (da && (newestAdded === null || da > newestAdded)) newestAdded = da;
    }
  }
  function isRecentlyAdded(dateStr) {
    // "NEW" = added in the most recent daily batch the bot pulled. Exact-match
    // the latest date so the initial bulk import doesn't light up the whole list.
    return !!dateStr && dateStr === newestAdded;
  }

  function render(keepCap) {
    if (!keepCap) state.renderCap = RENDER_CHUNK;
    computeNewestAdded();
    const rows = getView();
    renderTable(rows);
    renderMetrics(rows);
    renderResultCount(rows);
    syncSortHeaders();
  }

  function renderResultCount(rows) {
    el.resultCount.innerHTML =
      "Showing <strong>" + rows.length + "</strong> of " + DATA.length + " settlements";
  }

  function renderTable(allRows) {
    el.tableBody.innerHTML = "";
    el.emptyState.hidden = allRows.length > 0;
    const rows = allRows.slice(0, state.renderCap);
    const remaining = allRows.length - rows.length;
    const frag = document.createDocumentFragment();
    rows.forEach((d) => {
      const tr = document.createElement("tr");
      tr.tabIndex = 0;
      tr.setAttribute("role", "button");
      const amt = money(d.amount);
      const rt = d.record_type || "Settlement";
      const typeChip = rt !== "Settlement"
        ? ' <span class="badge badge-type">' + esc(rt) + "</span>"
        : "";
      const newChip = (isRecentlyAdded(d.date_added) && !isExpired(d))
        ? '<span class="badge badge-new">NEW</span> ' : "";
      const closedChip = isExpired(d)
        ? '<span class="badge badge-closed">CLOSED</span> ' : "";
      tr.innerHTML =
        '<td class="case-cell">' +
          '<div class="case-name">' + newChip + closedChip + esc(d.short_name) + "</div>" +
          '<div class="case-def">' + esc(d.defendant) + "</div>" +
        "</td>" +
        '<td><span class="badge badge-cat">' + esc(d.category) + "</span>" + typeChip + "</td>" +
        '<td class="num amount-cell">' +
          (amt ? esc(amt) : '<span class="amount-na">N/A</span>') +
        "</td>" +
        '<td class="num">' + (d.year != null ? esc(d.year) : "—") + "</td>" +
        '<td class="court-cell">' + esc(d.court || "—") + "</td>" +
        '<td class="num">' + (d.class_size != null ? esc(compact(d.class_size)) : "—") + "</td>" +
        '<td><span class="status ' + statusClass(d.status) + '">' + esc(d.status) + "</span></td>";
      tr.addEventListener("click", () => openDetail(d));
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(d); }
      });
      frag.appendChild(tr);
    });
    if (remaining > 0) {
      const tr = document.createElement("tr");
      tr.className = "show-more-row";
      tr.innerHTML = '<td colspan="7"><button class="btn btn-block">' +
        "Show " + Math.min(remaining, RENDER_CHUNK * 2).toLocaleString("en-US") +
        " more (" + remaining.toLocaleString("en-US") + " remaining)</button></td>";
      tr.querySelector("button").addEventListener("click", () => {
        state.renderCap += RENDER_CHUNK * 2;
        render(true);
      });
      frag.appendChild(tr);
    }
    el.tableBody.appendChild(frag);
  }

  function renderMetrics(rows) {
    const totalValue = rows.reduce((s, d) => s + (d.amount || 0), 0);
    const totalClass = rows.reduce((s, d) => s + (d.class_size || 0), 0);
    const cats = new Set(rows.map((d) => d.category));
    const largest = rows.reduce((m, d) => (d.amount > (m ? m.amount : 0) ? d : m), null);

    el.metrics.count.textContent = rows.length.toLocaleString("en-US");
    el.metrics.value.textContent = money(totalValue) || "$0";
    el.metrics.class.textContent = totalClass ? "~" + compact(totalClass) : "—";
    el.metrics.cats.textContent = cats.size;
    if (largest && largest.amount) {
      el.metrics.largest.textContent = money(largest.amount);
      el.metrics.largest.parentElement.title = largest.short_name;
    } else {
      el.metrics.largest.textContent = "—";
    }
  }

  function syncSortHeaders() {
    el.table.querySelectorAll("th[data-sort]").forEach((th) => {
      th.classList.remove("sorted", "asc", "desc");
      if (th.dataset.sort === state.sortKey) {
        th.classList.add("sorted", state.sortDir);
      }
    });
    el.sortSelect.value = state.sortKey + ":" + state.sortDir;
  }

  // ---------- Detail drawer ----------
  function detailRow(k, v, mono) {
    if (v == null || v === "") return "";
    return (
      '<div class="detail-row"><div class="k">' + esc(k) + "</div>" +
      '<div class="v' + (mono ? " mono" : "") + '">' + esc(v) + "</div></div>"
    );
  }

  // CourtListener docket search (free federal court database). We link rather
  // than auto-store a docket number, because automatic name-matching picks the
  // wrong case too often to trust in a firm's database.
  function clSearch(query) {
    return "https://www.courtlistener.com/?type=r&q=" + encodeURIComponent(query);
  }
  function docketRow(d) {
    var find = (d.short_name || d.case_name || "").replace(/^\$[\d.,]+[a-z]*\s+/i, "");
    if (d.defendant && d.defendant.indexOf("(") < 0) find += " " + d.defendant;
    var findLink = '<a href="' + esc(clSearch(find)) +
      '" target="_blank" rel="noopener">Find docket on CourtListener ↗</a>';
    var v = findLink;
    if (d.case_number) {
      var lookup = '<a href="' + esc(clSearch(d.case_number + " " + (d.defendant || ""))) +
        '" target="_blank" rel="noopener">look up ↗</a>';
      v = '<span class="mono">' + esc(d.case_number) + "</span> · " + lookup +
          '<div class="docket-find">' + findLink + "</div>";
    }
    return '<div class="detail-row"><div class="k">Court docket</div>' +
           '<div class="v">' + v + "</div></div>";
  }

  function openDetail(d) {
    const amt = money(d.amount);
    const rt = d.record_type || "Settlement";
    // Build a useful search (no exact-phrase quotes, which often return nothing).
    var sq = (d.short_name || d.case_name || "").replace(/^\$[\d.,]+[a-z]*\s+/i, "");
    if (d.defendant && d.defendant.indexOf("(") < 0) sq += " " + d.defendant;
    const searchUrl = "https://www.google.com/search?q=" +
      encodeURIComponent(sq + " class action settlement");
    // A few sources only expose a generic case-list page (no per-case URL) —
    // treat those as "no direct source" and offer the search instead.
    const GENERIC = ["rg2claims.com/cases.html"];
    const realSource = d.source_url && GENERIC.every(function (g) { return d.source_url.indexOf(g) < 0; });
    el.detailBody.innerHTML =
      '<div class="detail-eyebrow">' + esc(d.category) +
        (rt !== "Settlement" ? ' · <span class="eyebrow-type">' + esc(rt) + "</span>" : "") +
      "</div>" +
      '<h2 class="detail-title">' + esc(d.short_name) + "</h2>" +
      '<p class="detail-def">' + esc(d.defendant) + "</p>" +
      '<div class="detail-hero">' +
        '<div><div class="h-val">' + (amt || "N/A") + '</div><div class="h-lbl">Settlement</div></div>' +
        '<div><div class="h-val">' + esc(d.year) + '</div><div class="h-lbl">Year</div></div>' +
        '<div><div class="h-val">' + (d.class_size != null ? "~" + compact(d.class_size) : "—") + '</div><div class="h-lbl">Class Size</div></div>' +
      "</div>" +
      '<p class="detail-desc">' + esc(d.description) + "</p>" +
      '<div class="detail-grid">' +
        detailRow("Matter", d.case_name) +
        detailRow("Record type", rt) +
        detailRow("Status", d.status) +
        detailRow("Court", d.court_full || d.court) +
        detailRow("Judge", d.judge) +
        docketRow(d) +
        detailRow("Class size", d.class_size != null ? fullNum(d.class_size) + " members" : null) +
        detailRow("Settlement", amt ? amt + " (" + fullNum(d.amount) + ")" : "Non-monetary / N/A") +
        detailRow("Attorneys' fees", d.fee_award != null ? money(d.fee_award) + " (" + fullNum(d.fee_award) + ")" : null) +
        detailRow("Source", d.source) +
        '<div class="detail-row"><div class="k">Link</div><div class="v">' +
          (realSource
            ? '<a href="' + esc(d.source_url) + '" target="_blank" rel="noopener">View source ↗</a>'
            : '<a href="' + esc(searchUrl) + '" target="_blank" rel="noopener">Search this case ↗</a>') +
        "</div></div>" +
        (d.date_added ? detailRow("Added", d.date_added) : "") +
      "</div>";
    el.detail.hidden = false;
    el.overlay.hidden = false;
    el.detailClose.focus();
  }

  function closeDetail() {
    el.detail.hidden = true;
    el.overlay.hidden = true;
  }

  // ---------- CSV export ----------
  function csvCell(v) {
    if (v == null) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function exportCSV() {
    const rows = getView();
    const cols = [
      ["case_name", "Case Name"], ["short_name", "Short Name"], ["defendant", "Defendant"],
      ["category", "Practice Area"], ["record_type", "Record Type"],
      ["amount", "Settlement Amount (USD)"], ["year", "Year"],
      ["status", "Status"], ["court", "Court"], ["court_full", "Court (full)"],
      ["judge", "Judge"], ["case_number", "Docket/MDL"], ["class_size", "Class Size"],
      ["fee_award", "Attorneys' Fees (USD)"], ["description", "Description"],
      ["source", "Source"], ["source_url", "Source URL"],
    ];
    const lines = [cols.map((c) => csvCell(c[1])).join(",")];
    rows.forEach((d) => {
      lines.push(cols.map((c) => csvCell(d[c[0]])).join(","));
    });
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "settlements-export.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ---------- Events ----------
  function bindEvents() {
    let t;
    el.search.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(() => { state.search = el.search.value.trim(); render(); }, 120);
    });

    el.yearMin.addEventListener("change", () => {
      state.yearMin = el.yearMin.value ? parseInt(el.yearMin.value, 10) : null;
      render();
    });
    el.yearMax.addEventListener("change", () => {
      state.yearMax = el.yearMax.value ? parseInt(el.yearMax.value, 10) : null;
      render();
    });
    el.amountMin.addEventListener("change", () => {
      const v = el.amountMin.value;
      state.amountMin = (v === "has" || v === "none") ? v : (parseInt(v, 10) || 0);
      render();
    });

    el.sortSelect.addEventListener("change", () => {
      const [k, dir] = el.sortSelect.value.split(":");
      state.sortKey = k; state.sortDir = dir;
      render();
    });

    if (el.showClosed) {
      el.showClosed.addEventListener("change", () => {
        state.showClosed = el.showClosed.checked;
        render();
      });
    }

    el.table.querySelectorAll("th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (state.sortKey === key) {
          state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
        } else {
          state.sortKey = key;
          state.sortDir = (key === "short_name" || key === "category") ? "asc" : "desc";
        }
        render();
      });
    });

    document.querySelectorAll(".link-btn[data-clear]").forEach((b) => {
      b.addEventListener("click", () => {
        const which = b.dataset.clear;
        const key = which === "rtype" ? "record_type" : which;
        setForKey(key).clear();
        const container = which === "category" ? el.filterCategory
          : which === "rtype" ? el.filterRtype : el.filterStatus;
        container.querySelectorAll("input").forEach((i) => (i.checked = false));
        render();
      });
    });

    el.resetBtn.addEventListener("click", () => {
      state.search = "";
      state.categories.clear();
      state.statuses.clear();
      state.rtypes.clear();
      state.yearMin = state.yearMax = null;
      state.amountMin = 0;
      state.sortKey = "amount"; state.sortDir = "desc";
      el.search.value = "";
      el.yearMin.value = ""; el.yearMax.value = "";
      el.amountMin.value = "0";
      document.querySelectorAll(".checkbox-list input").forEach((i) => (i.checked = false));
      render();
    });

    el.exportBtn.addEventListener("click", exportCSV);
    el.refreshBtn.addEventListener("click", refreshData);
    el.detailClose.addEventListener("click", closeDetail);
    el.overlay.addEventListener("click", closeDetail);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeDetail();
    });
  }

  // ---------- Live data ----------
  function dropDead(list) {
    // Records whose page turned out to be a 404 / generic page are flagged dead.
    return (list || []).filter(function (r) { return !r.dead; });
  }
  async function loadData() {
    try {
      const res = await fetch("api/settlements", { cache: "no-store" });
      if (!res.ok) throw new Error("api unavailable");
      const json = await res.json();
      DATA = dropDead(json.settlements || json || []);
      state.online = true;
      state.lastUpdated = json.last_updated || null;
    } catch (e) {
      // Opened directly from disk (file://) or no server — use the embedded data.
      DATA = dropDead(window.SETTLEMENTS || []);
      state.online = false;
      state.lastUpdated = null;
    }
  }

  var isLocalFile = location.protocol === "file:";

  function updateLastUpdated() {
    if (!state.online) {
      el.lastUpdated.textContent = isLocalFile
        ? "Offline · run server.py for live refresh"
        : "Updates automatically every few hours";
      el.lastUpdated.classList.add("offline");
      return;
    }
    el.lastUpdated.classList.remove("offline");
    if (state.lastUpdated) {
      const d = new Date(state.lastUpdated);
      el.lastUpdated.textContent = "Updated " + d.toLocaleDateString() + " " +
        d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } else {
      el.lastUpdated.textContent = "Click Refresh to pull latest";
    }
  }

  let toastTimer;
  function showToast(htmlMsg, isError) {
    el.toast.innerHTML = htmlMsg;
    el.toast.classList.toggle("toast-error", !!isError);
    el.toast.hidden = false;
    void el.toast.offsetWidth; // reflow so the transition runs
    el.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.toast.classList.remove("show");
      setTimeout(() => { el.toast.hidden = true; }, 250);
    }, isError ? 7000 : 5000);
  }

  async function refreshData() {
    if (!state.online) {
      showToast(isLocalFile
        ? "Live refresh needs the local server. Run <code>python server.py</code>, then open the URL it prints."
        : "This site refreshes itself automatically every few hours — the data is already kept current, no action needed.",
        !isLocalFile ? false : true);
      return;
    }
    const label = el.refreshBtn.querySelector(".btn-label");
    const prevLabel = label.textContent;
    el.refreshBtn.disabled = true;
    el.refreshBtn.classList.add("loading");
    label.textContent = "Pulling latest…";
    try {
      const res = await fetch("api/refresh", { method: "POST" });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || "refresh failed");
      await loadData();
      buildFilters();
      render();
      updateLastUpdated();
      const srcBits = Object.entries(json.sources || {})
        .map((kv) => esc(kv[0]) + " " + kv[1]).join(" · ");
      const typeBits = Object.entries(json.by_type || {})
        .map((kv) => esc(kv[0]) + " " + kv[1]).join(" · ");
      const noteBits = (json.notes && json.notes.length)
        ? "<br><span style='opacity:.7'>" + json.notes.map(esc).join("; ") + "</span>" : "";
      if (json.added > 0) {
        showToast("✓ Added <strong>" + json.added + "</strong> new record" +
          (json.added === 1 ? "" : "s") +
          (typeBits ? " &nbsp;<span style='opacity:.85'>(" + typeBits + ")</span>" : "") +
          " &nbsp;<span style='opacity:.7'>" + srcBits + " · total " + json.total + "</span>" +
          noteBits);
      } else {
        showToast("Up to date — no new records found &nbsp;<span style='opacity:.7'>" + srcBits + "</span>" + noteBits);
      }
    } catch (e) {
      showToast("Refresh failed: " + esc(String((e && e.message) || e)), true);
    } finally {
      el.refreshBtn.disabled = false;
      el.refreshBtn.classList.remove("loading");
      label.textContent = prevLabel;
    }
  }

  // ---------- Init ----------
  async function init() {
    await loadData();
    // Default view: Settlements only (the others are one click away).
    if (DATA.some((d) => (d.record_type || "Settlement") === "Settlement")) {
      state.rtypes.add("Settlement");
    }
    buildFilters();
    bindEvents();
    render();
    updateLastUpdated();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
