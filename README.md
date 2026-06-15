# SettleSearch — Live Settlement Database

A searchable database of class-action, mass-tort, and regulatory matters with a
live **Refresh** button that pulls from ~25 public sources on demand. It ingests
**everything those sites post** — settlements, filed lawsuits, investigations, and
news/roundups, with or without a dollar amount — and **tags each record by type**
so you can filter to exactly what you want. Every pulled record links back to its
source. Dependency-free; you own and control it.

## Two ways to run it

### 1. Live mode (recommended) — real-time refresh enabled
```powershell
cd "C:\Users\DSamson\.claude\Settlement"
python server.py
```
Open the URL it prints (**http://localhost:8765**) and click **⟳ Refresh data**.
Pure Python standard library — no `pip install`.

### 2. Offline mode — just open the file
Double-click `index.html`. Runs from disk on the last-saved data (`data.js`).
Everything works except the live Refresh button.

## What it does

- **⟳ Refresh data** — pulls the latest from every source, dedups, merges new records,
  and reports how many were added, broken down by type.
- **Record Type filter** — one click to show only **Settlements**, **Lawsuits Filed**,
  **Investigations**, or **News & Guides** (or any combination).
- **Full-text search** across case, defendant, court, judge, docket, description, source.
- **Filters** — practice area, status, year range, and an amount filter with
  **"Has dollar amount" / "No amount listed"** options.
- **Sort** by amount, year, class size, or name.
- **Detail view** — full record plus a **link to the source** (a Google search link if
  a record has no direct URL) so you can verify any figure.
- **CSV export** of the current view (includes the source URL column).
- Handles 10,000+ records: the table renders in chunks with a **Show more** control.

## Where the live data comes from

Everything is public and needs no API key. Sources are grouped by role:

**Fresh, dated headlines (RSS):**
Top Class Actions · FTC · AboutLawsuits · LawyersAndSettlements · BigClassAction ·
Lawsuit Information Center

**Aggregator catalogs (sitemaps — broad coverage):**
ClaimDepot · ClassAction.org · OpenClassActions · ClassActionBuddy · Dapeer Law ·
InjuryClaims · Catch (choosecatch) · Settlemate · ClassActionRebates

**Claims administrators (official case lists):**
RG/2 Claims (JSON, with court + docket) · Strategic Claims · Verita Global · Angeion Group

**Government / regulators:**
SEC (litigation releases + administrative proceedings) · CFPB · DOJ ·
California AG · Washington AG · NY AG · NAAG (state-AG multistate cases)

Each record stores only the **facts** (case, amount, type, date) plus a one-line
summary and a **link back to the original source** — never reproduced article text.

### How "ingest everything, tag by type" works

The pipeline no longer excludes non-settlements. Every item is ingested and
classified by `derive_record_type()` into one of:

| Record type | Examples |
|-------------|----------|
| **Settlement** | "$45M Avem Health data breach settlement", "Anheuser-Busch settlement" |
| **Lawsuit Filed** | "X sues Y", "Z hit with class action", complaints |
| **Investigation** | "attorneys reviewing…", "FTC investigating…" |
| **News & Guides** | "10 settlements you can claim this month", how-to/FAQ posts |

Filter to **Settlement** for the clean settlement list; switch on the others when you
want the full pipeline of filed cases, probes, and claim roundups.

### Data quality notes (honest trade-offs)

- **Amounts:** only a minority of records carry a parsed dollar amount — many sitemap
  slugs and government feeds don't put the figure in the title. Use the **"No amount
  listed"** filter to find them, then click through to the source. Amount parsing
  rejects implausible values: a stray number won't become a "$480B settlement," and
  slug shorthand like `267b` (which means $2.67B, not $267B) is discarded rather than
  shown wrong. Authoritative big-ticket figures live on the ~79 **curated** records.
- **Years:** sitemap-sourced records have no date in the feed, so their **year is blank**
  and their case name is derived from the page slug (recognizable, but rougher than the
  curated and RSS records). Source links let you confirm details.
- **Cross-source duplicates:** the same case often appears on several sites. Dedup
  collapses near-identical names, but distinct slugs from different sites may both
  survive — which means you get multiple source links for that case.
- **NAAG** blocks automated fetches from datacenter IPs (HTTP 403); it may work from a
  home connection and fails gracefully (logged, never crashes the refresh).

### Refresh from the command line
```powershell
python server.py --refresh-once     # pull once, print a JSON summary, exit
```

### Adding or removing sources
Each connector in `server.py` returns a list of normalized records and never raises.
Add one to the `SOURCES` list to enable it. Generic helpers cover the common cases:
`_fetch_rss(...)`, `_fetch_sitemap_settlements(...)`, plus bespoke JSON/HTML connectors
(`fetch_rg2claims`, `fetch_ny_ag`). CourtListener (`fetch_courtlistener`) is wired but
**off** by default (it returns opinions *about* class actions, not settlements).

## Files

| File | Purpose |
|------|---------|
| `server.py` | Local web server + the ~25-source live pipeline (stdlib only) |
| `index.html` / `styles.css` / `app.js` | The web app |
| `settlements.json` | Live data store (read + updated by the server) |
| `settlements.seed.json` | Curated baseline of ~79 verified marquee settlements (for reset) |
| `data.js` | Offline fallback copy of the data |
| `.claude/launch.json` | Preview-server config |

**Reset to the curated baseline:** `Copy-Item settlements.seed.json settlements.json -Force`

## Notes
- No external libraries or build step — vanilla HTML/CSS/JS + Python stdlib.
- The server binds to `127.0.0.1` only (local-only; not exposed to your network).
