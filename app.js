/* ===== SettleSearch — application logic ===== */
(function () {
  "use strict";

  let DATA = [];

  // External-facing copy. Mirrors TAGLINE / DISCLAIMER / REPORT_EMAIL in
  // server.py -- change both together.
  const DISCLAIMER =
    "L&K Labs Settlement Tape - BETA. Fully automated and unaudited: records are " +
    "scraped from public sources, may be stale, wrong or duplicated, and nobody at " +
    "Levi & Korsinsky reviews them. Informational only; not legal, financial or " +
    "investment advice; do not rely on any figure without checking the docket.";
  const REPORT_EMAIL = "dsamson@zlk.com";
  // Reserved for the New York attorney-advertising label if counsel calls for it.
  const ATTORNEY_AD_LINE = "";

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
    quick: null,        // tile filter: null | "new7" | "closing"
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
    ribbonStamp: document.getElementById("ribbonStamp"),
    stampDate: document.getElementById("stampDate"),
    reportLinks: [document.getElementById("reportLink"), document.getElementById("reportLinkFooter")],
    adSlots: [document.getElementById("adSlotTable"), document.getElementById("adSlotFooter")],
    tiles: {
      open: document.getElementById("t-open"),
      new7: document.getElementById("t-new7"),
      largest: document.getElementById("t-largest"),
      busiest: document.getElementById("t-busiest"),
      closing: document.getElementById("t-closing"),
    },
    m: {
      open: document.getElementById("m-open"),
      total: document.getElementById("m-total"),
      new7: document.getElementById("m-new7"),
      new7v: document.getElementById("m-new7v"),
      largest: document.getElementById("m-largest"),
      largestn: document.getElementById("m-largestn"),
      busiest: document.getElementById("m-busiest"),
      busiestn: document.getElementById("m-busiestn"),
      closing: document.getElementById("m-closing"),
      codedpct: document.getElementById("m-codedpct"),
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
  function daysAgoISO(n) {
    var d = new Date(); d.setDate(d.getDate() - n);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
           "-" + String(d.getDate()).padStart(2, "0");
  }
  var WEEK_AGO = daysAgoISO(7), MONTH_AGO = daysAgoISO(30), MONTH_AHEAD = daysAgoISO(-30);
  function isExpired(d) {
    return !!d.claim_deadline && d.claim_deadline < TODAY;
  }
  function isClosingSoon(d) {
    return !!d.claim_deadline && d.claim_deadline >= TODAY && d.claim_deadline <= MONTH_AHEAD;
  }
  // When the bot last touched the record: page re-read date, else first-seen date.
  function lastSeen(d) {
    return d.enriched_at || d.date_added || null;
  }

  function matches(d) {
    // Hide closed settlements unless the user opts in or is searching for one.
    if (isExpired(d) && !state.showClosed && !state.search) return false;
    if (state.quick === "new7" && !(d.date_added && d.date_added >= WEEK_AGO)) return false;
    if (state.quick === "closing" && !isClosingSoon(d)) return false;
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
    renderMetrics();
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
        '<td class="court-cell"><span title="' + esc(d.court_full || d.court || "") + '">' + esc(d.court || "—") + "</span></td>" +
        '<td class="num">' + (d.class_size != null ? esc(compact(d.class_size)) : "—") + "</td>" +
        '<td><span class="status ' + statusClass(d.status) + '">' + esc(d.status) + "</span></td>" +
        '<td class="source-cell">' + sourceLink(d) + "</td>" +
        '<td class="seen-cell">' + esc(lastSeen(d) || "—") + "</td>";
      tr.addEventListener("click", () => openDetail(d));
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(d); }
      });
      frag.appendChild(tr);
    });
    if (remaining > 0) {
      const tr = document.createElement("tr");
      tr.className = "show-more-row";
      tr.innerHTML = '<td colspan="9"><button class="btn btn-block">' +
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

  // Tiles describe the whole tape (all live Settlement records), not the current
  // view, so they read the same no matter what is filtered. Each is a filter.
  function renderMetrics() {
    const all = DATA.filter((d) => (d.record_type || "Settlement") === "Settlement");
    const open = all.filter((d) => !isExpired(d));
    const coded = all.filter((d) => d.amount);
    const new7 = all.filter((d) => d.date_added && d.date_added >= WEEK_AGO);
    const new30 = all.filter((d) => d.date_added && d.date_added >= MONTH_AGO);
    const closing = all.filter(isClosingSoon);
    const largest = new30.reduce((m, d) => ((d.amount || 0) > (m ? m.amount : 0) ? d : m), null);
    const byCat = {};
    new30.forEach((d) => { byCat[d.category] = (byCat[d.category] || 0) + 1; });
    const busiest = Object.keys(byCat).sort((a, b) => byCat[b] - byCat[a])[0] || null;

    el.m.open.textContent = open.length.toLocaleString("en-US");
    el.m.total.textContent = all.length.toLocaleString("en-US");
    el.m.new7.textContent = new7.length.toLocaleString("en-US");
    el.m.new7v.textContent = money(new7.reduce((s, d) => s + (d.amount || 0), 0)) || "$0";
    if (largest) {
      el.m.largest.textContent = money(largest.amount);
      el.m.largestn.textContent = (largest.short_name || "").slice(0, 40) + " →";
      el.tiles.largest.dataset.id = largest.id;
    } else {
      el.m.largest.textContent = "—";
      el.m.largestn.textContent = "nothing coded this month";
    }
    el.m.busiest.textContent = busiest || "—";
    el.m.busiestn.textContent = busiest ? byCat[busiest].toLocaleString("en-US") : "—";
    el.tiles.busiest.dataset.cat = busiest || "";
    el.m.closing.textContent = closing.length.toLocaleString("en-US");
    el.m.codedpct.textContent = all.length
      ? Math.round(100 * coded.length / all.length) + "%" : "—";

    el.tiles.open.classList.toggle("active", state.showClosed);
    el.tiles.new7.classList.toggle("active", state.quick === "new7");
    el.tiles.closing.classList.toggle("active", state.quick === "closing");
    el.tiles.busiest.classList.toggle("active",
      !!busiest && state.categories.size === 1 && state.categories.has(busiest));
  }

  // "As of" stamps: the newest date the bot wrote anything, shown in the ribbon,
  // the table footer and the CSV.
  function asOfDate() {
    var latest = null;
    for (var i = 0; i < DATA.length; i++) {
      var s = lastSeen(DATA[i]);
      if (s && (latest === null || s > latest)) latest = s;
    }
    return latest || TODAY;
  }
  function renderStamps() {
    var asOf = asOfDate();
    if (el.ribbonStamp) el.ribbonStamp.textContent = "as of " + asOf + " · refreshes every 6h · 0 humans involved";
    if (el.stampDate) el.stampDate.textContent = asOf;
    el.reportLinks.forEach(function (a) { if (a) a.href = reportHref(null); });
    el.adSlots.forEach(function (n) { if (n) n.textContent = ATTORNEY_AD_LINE; });
  }
  function reportHref(d) {
    var subject = "Settlement Tape: bad record" + (d ? " " + d.id : "");
    var body = d
      ? "Record: " + d.id + "\nCase: " + (d.short_name || "") + "\nSource: " + (d.source_url || d.source || "") +
        "\n\nWhat's wrong:\n"
      : "Record (case name or link):\n\nWhat's wrong:\n";
    return "mailto:" + REPORT_EMAIL + "?subject=" + encodeURIComponent(subject) +
           "&body=" + encodeURIComponent(body);
  }
  function sourceLink(d) {
    var GENERIC = ["rg2claims.com/cases.html"];
    var real = d.source_url && GENERIC.every(function (g) { return d.source_url.indexOf(g) < 0; });
    if (!real) return esc(d.source || "—");
    return '<a href="' + esc(d.source_url) + '" target="_blank" rel="noopener" ' +
      'title="Open the source page" onclick="event.stopPropagation()">' + esc(d.source) + " ↗</a>";
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
  // Direct link to the claims administrator — where the user actually files,
  // instead of hopping through an aggregator.
  function officialRow(d) {
    if (!d.official_url) return "";
    return '<div class="detail-row"><div class="k">Official site</div>' +
      '<div class="v"><a class="official-link" href="' + esc(d.official_url) +
      '" target="_blank" rel="noopener">File at the claims administrator ↗</a></div></div>';
  }
  // Complaint / settlement-agreement / notice PDFs pulled from the administrator.
  function docsRow(d) {
    if (!d.documents || !d.documents.length) return "";
    var items = d.documents.map(function (doc) {
      return '<a class="doc-link" href="' + esc(doc.url) +
        '" target="_blank" rel="noopener">' + esc(doc.label) + " ↗</a>";
    }).join("");
    return '<div class="detail-row"><div class="k">Documents</div>' +
      '<div class="v doc-list">' + items + "</div></div>";
  }
  function docketRow(d) {
    // CourtListener is inconsistent, so only fall back to it when we have no
    // administrator site and no documents to offer.
    if (d.official_url || (d.documents && d.documents.length)) {
      return d.case_number
        ? '<div class="detail-row"><div class="k">Case no.</div><div class="v mono">' +
            esc(d.case_number) + "</div></div>"
        : "";
    }
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
        officialRow(d) +
        docsRow(d) +
        docketRow(d) +
        detailRow("Class size", d.class_size != null ? fullNum(d.class_size) + " members" : null) +
        detailRow("Settlement", amt ? amt + " (" + fullNum(d.amount) + ")" : "Non-monetary / N/A") +
        detailRow("Attorneys' fees", d.fee_award != null ? money(d.fee_award) + " (" + fullNum(d.fee_award) + ")" : null) +
        detailRow("Class counsel", d.counsel) +
        detailRow("Source", d.source) +
        '<div class="detail-row"><div class="k">Link</div><div class="v">' +
          (d.official_url
            ? '<a href="' + esc(d.official_url) + '" target="_blank" rel="noopener">Official settlement site ↗</a>' +
              (realSource ? ' · <a href="' + esc(d.source_url) + '" target="_blank" rel="noopener">via ' + esc(d.source) + " ↗</a>" : "")
            : realSource
              ? '<a href="' + esc(d.source_url) + '" target="_blank" rel="noopener">View source ↗</a>'
              : '<a href="' + esc(searchUrl) + '" target="_blank" rel="noopener">Search this case ↗</a>') +
        "</div></div>" +
        (d.date_added ? detailRow("First seen", d.date_added) : "") +
        (d.enriched_at ? detailRow("Last checked", d.enriched_at) : "") +
      "</div>" +
      '<a class="report-link" href="' + esc(reportHref(d)) + '">⚑ Report a bad record</a>';
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
      ["fee_award", "Attorneys' Fees (USD)"], ["counsel", "Class Counsel"], ["description", "Description"],
      ["source", "Source"], ["source_url", "Source URL"],
      ["date_added", "First Seen"], ["enriched_at", "Last Checked"], ["claim_deadline", "Claim Deadline"],
    ];
    // The file travels without the page around it, so the disclaimer is row 1
    // (cell A1 in Excel) and the as-of stamp is row 2. Headers start on row 3.
    const asOf = asOfDate();
    const lines = [
      csvCell(DISCLAIMER + (ATTORNEY_AD_LINE ? " " + ATTORNEY_AD_LINE : "")),
      csvCell("As of " + asOf + " · " + rows.length.toLocaleString("en-US") +
              " rows (current view) · report errors: " + REPORT_EMAIL),
      cols.map((c) => csvCell(c[1])).join(","),
    ];
    rows.forEach((d) => {
      lines.push(cols.map((c) => csvCell(d[c[0]])).join(","));
    });
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "lk-labs-settlement-tape-BETA-" + asOf + ".csv";
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
      state.quick = null;
      state.showClosed = false; if (el.showClosed) el.showClosed.checked = false;
      state.sortKey = "date_added"; state.sortDir = "desc";
      el.search.value = "";
      el.yearMin.value = ""; el.yearMax.value = "";
      el.amountMin.value = "0";
      document.querySelectorAll(".checkbox-list input").forEach((i) => (i.checked = false));
      render();
    });

    el.exportBtn.addEventListener("click", exportCSV);
    el.refreshBtn.addEventListener("click", refreshData);

    // Tiles: each one is a filter or opens a record.
    el.tiles.open.addEventListener("click", () => {
      state.showClosed = !state.showClosed;
      if (el.showClosed) el.showClosed.checked = state.showClosed;
      render();
    });
    el.tiles.new7.addEventListener("click", () => {
      state.quick = state.quick === "new7" ? null : "new7";
      if (state.quick) { state.sortKey = "date_added"; state.sortDir = "desc"; }
      render();
    });
    el.tiles.closing.addEventListener("click", () => {
      state.quick = state.quick === "closing" ? null : "closing";
      if (state.quick) { state.showClosed = false; if (el.showClosed) el.showClosed.checked = false; }
      render();
    });
    el.tiles.busiest.addEventListener("click", () => {
      const cat = el.tiles.busiest.dataset.cat;
      if (!cat) return;
      const on = state.categories.size === 1 && state.categories.has(cat);
      state.categories.clear();
      if (!on) state.categories.add(cat);
      el.filterCategory.querySelectorAll("input").forEach((i) => { i.checked = !on && i.value === cat; });
      render();
    });
    el.tiles.largest.addEventListener("click", () => {
      const id = el.tiles.largest.dataset.id;
      const d = id && DATA.find((x) => x.id === id);
      if (d) openDetail(d);
    });
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
      // No local server (e.g. GitHub Pages). Fetch the published dataset directly
      // with a unique cache-buster so a stale browser/CDN copy can't be served —
      // this is what makes daily updates actually show up. Fall back to the inline
      // data.js only when even that fails (opened from disk via file://).
      try {
        const r2 = await fetch("settlements.json?t=" + Date.now(), { cache: "no-store" });
        if (!r2.ok) throw new Error("no json");
        DATA = dropDead(await r2.json());
      } catch (e2) {
        DATA = dropDead(window.SETTLEMENTS || []);
      }
      state.online = false;
      state.lastUpdated = null;
    }
  }

  var isLocalFile = location.protocol === "file:";

  function updateLastUpdated() {
    if (!state.online) {
      el.lastUpdated.textContent = isLocalFile
        ? "Offline · run server.py for live refresh"
        : "Refreshed " + asOfDate() + " · auto every 6h";
      el.lastUpdated.classList.toggle("offline", isLocalFile);
      // On the static site the button can't do anything; don't show a dead control.
      el.refreshBtn.hidden = !isLocalFile;
      return;
    }
    el.refreshBtn.hidden = false;
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
    renderStamps();
    updateLastUpdated();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
