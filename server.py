#!/usr/bin/env python3
"""
SettleSearch — local data server + live settlement pipeline.

Serves the static web app AND exposes a small JSON API:

    GET  /api/settlements   -> { settlements: [...], last_updated: "..." }
    POST /api/refresh       -> pulls the latest settlements from public sources,
                               merges new ones, and returns a summary.

Live sources (no API key required):
  * FTC press releases (RSS)        — consumer-protection settlements
  * CourtListener API (federal courts) — recent class-action settlement opinions

Run it:
    python server.py                # serve on http://localhost:8765
    python server.py --refresh-once # run one refresh from the command line and exit
    python server.py --port 9000    # custom port

Pure standard library — no pip install needed.
"""
import json, os, re, ssl, sys, html, gzip, sqlite3, threading, time
import urllib.request, urllib.error
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "settlements.json")   # bundled seed / baseline
DATA_JS = os.path.join(ROOT, "data.js")          # offline fallback export
SEED = os.path.join(ROOT, "settlements.seed.json")
# Durable store. Point DB_PATH at a persistent disk in production (e.g.
# /data/settlements.db) so every refresh is saved permanently across restarts.
DB_PATH = os.environ.get("DB_PATH", os.path.join(ROOT, "settlements.db"))
UA = "SettleSearch/1.0 (settlement research; contact: admin@example.com)"
SITE_NAME = os.environ.get("SITE_NAME", "")      # optional firm branding

# Canonical field set every record carries (keeps the front-end happy).
FIELDS = ["id", "case_name", "short_name", "defendant", "amount", "category",
          "record_type", "year", "status", "court", "court_full", "judge",
          "case_number", "class_size", "fee_award", "description", "source",
          "source_url", "date_added", "enriched_at"]

# Free-text notes connectors can attach to a refresh (e.g. "capped at N").
REFRESH_NOTES = []


# ----------------------------------------------------------------------------
# HTTP helper — verifies TLS normally, falls back to unverified for machines
# behind a corporate SSL-inspection proxy.
# ----------------------------------------------------------------------------
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


def http_get(url, timeout=25, headers=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        return urllib.request.urlopen(req, timeout=timeout).read()
    except (ssl.SSLError, urllib.error.URLError) as e:
        if isinstance(e, urllib.error.HTTPError):
            raise
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=timeout, context=ctx).read()


# ----------------------------------------------------------------------------
# Text extraction helpers
# ----------------------------------------------------------------------------
_MULT = {"billion": 1e9, "bn": 1e9, "b": 1e9,
         "million": 1e6, "mm": 1e6, "m": 1e6,
         "thousand": 1e3, "k": 1e3}
_AMT_RE = re.compile(r"\$\s?([\d][\d,]*(?:\.\d+)?)\s*(billion|bn|b|million|mm|m|thousand|k)?\b",
                     re.IGNORECASE)


def parse_amount(text):
    """Return the largest USD figure mentioned in text, or None."""
    if not text:
        return None
    best = None
    for num, unit in _AMT_RE.findall(text):
        try:
            val = float(num.replace(",", ""))
        except ValueError:
            continue
        if unit:
            val *= _MULT[unit.lower()]
        val = int(round(val))
        # Ignore tiny per-person figures and implausible parses (a stray number
        # in prose becoming a half-trillion-dollar "settlement"). No real
        # class-action settlement approaches $50B.
        if 10000 <= val <= 50_000_000_000 and (best is None or val > best):
            best = val
    return best


_CATEGORY_RULES = [
    ("Data Breach", ["data breach", "data security", "cyberattack", "cyber attack",
                     "hacked", "breach exposed", "ransomware", "personal information was"]),
    ("Privacy", ["biometric", "bipa", "facial recognition", "privacy", "wiretap",
                 "location data", "tracking", "eavesdrop", "voiceprint", "video privacy"]),
    ("Antitrust", ["antitrust", "monopoly", "monopoli", "price-fixing", "price fixing",
                   "anticompetitive", "no-poach", "conspiracy to fix"]),
    ("Securities", ["securities", "shareholder", "investor", "10b-5", "ponzi",
                    "misled investors", "stock"]),
    ("TCPA", ["tcpa", "robocall", "telephone consumer protection", "unwanted text",
              "autodialer", "do-not-call", "do not call"]),
    ("Pharmaceutical", ["opioid", "pharmaceutical", "drug maker", "prescription",
                        "fda", "medication", "talc", "vioxx"]),
    ("Environmental", ["emissions", "oil spill", "contaminat", "pfas", "groundwater",
                       "pollution", "wildfire", "environmental"]),
    ("Employment", ["wage", "overtime", "misclassif", "employee", "labor", "workers were"]),
    ("Product Liability", ["defect", "recall", "airbag", "vehicle", "injuries caused",
                           "product liability", "earplug"]),
]


def classify(text):
    t = (text or "").lower()
    for cat, kws in _CATEGORY_RULES:
        if any(k in t for k in kws):
            return cat
    return "Consumer Protection"


# Record types: everything gets ingested; this tag is what makes the catch-all
# content easy to filter in the UI.
RT_SETTLEMENT = "Settlement"        # confirmed / claimable / finalized settlements
RT_ANNOUNCEMENT = "Announcement"    # announced, proposed, or rumored settlements
RT_LAWSUIT = "Lawsuit Filed"
RT_INVESTIGATION = "Investigation"
RT_REGULATORY = "Regulatory"        # govt enforcement actions/orders (non-settlement)
RT_NEWS = "News & Guides"

_RT_NEWS_PAT = re.compile(
    r"(you can claim|how to (file|claim|submit|get)|what you need to know|"
    r"everything you need to know|here'?s how|how to get (money|paid)|"
    r"what happens to|who'?s getting paid|whos getting paid|learn about|"
    r"deadline[s]? (this|in|for)|^\s*(top\s+)?\d+\s+(open\s+)?class action|"
    r"settlements? (to watch|roundup)|class action roundup|"
    r"average .{0,30}(settlement|verdict)|settlements? and verdicts?|"
    r"guide\b|faq\b)", re.I)
# News-section URL paths: a page filed under a site's news section reports ON a
# settlement, it isn't the claimable settlement record itself.
_NEWS_PATH_RE = re.compile(r"/(news|class-action-in-the-news|lawsuit-news)/", re.I)
_RT_INVESTIGATION_PAT = re.compile(
    r"(investigat\w+|attorneys? (are )?reviewing|under (review|scrutiny)|probe\b)", re.I)
_RT_SETTLEMENT_PAT = re.compile(
    r"(settl\w+|agrees? to pay|agreed to pay|will pay|to pay \$|refunds? (going|issued)|"
    r"judge approves|final approval|preliminary approval|consent (order|decree))", re.I)
_RT_LAWSUIT_PAT = re.compile(
    r"(lawsuit|sues?\b|sued\b|files? (suit|complaint|motion|charges)|hit with|"
    r"faces? (class action|suit|claims)|alleg\w+|accus\w+|complaint filed|seeks comment)", re.I)

# Finalized/claimable signals → a verified Settlement (these OVERRIDE the
# announcement signals: an approved or claimable deal is a real settlement).
_RT_FINAL_PAT = re.compile(
    r"(final approval|finally approved|judge approv\w+|court approv\w+|"
    r"approved the settlement|settlement approved|preliminary approval|"
    r"consent (order|decree|judgment)|settled\b|claims? (administrator|deadline|period|process)|"
    r"file (a )?claim|submit (a )?claim|claim form|payout|distribution|valid claim)", re.I)
# Not-yet-final signals → an Announcement / Rumor (news that a deal is coming).
_RT_ANNOUNCE_PAT = re.compile(
    r"(reach\w* (a |an |the )?settlement|settlement (was |is |has been |to be )?reach\w*|"
    r"announc\w+|proposed settlement|tentative\w*|in talks|nearing (a )?settlement|"
    r"rumor\w*|reportedly|may settle|could settle|set to settle|expected to settle|"
    r"agree\w* to settle|settlement talks|to settle (claims|charges|allegations|lawsuit|suit))",
    re.I)


def derive_record_type(text):
    # Normalize curly quotes so patterns like "who's getting paid" match titles
    # that use Unicode apostrophes (’) from news feeds.
    t = (text or "").replace("’", "'").replace("‘", "'").strip()
    if _RT_NEWS_PAT.search(t):
        return RT_NEWS
    if _RT_INVESTIGATION_PAT.search(t):
        return RT_INVESTIGATION
    if _RT_SETTLEMENT_PAT.search(t):
        # Verified settlement if finalized/claimable; otherwise, if the wording is
        # "reaches/proposed/rumored…", it's an announcement, not a banked settlement.
        if _RT_FINAL_PAT.search(t):
            return RT_SETTLEMENT
        if _RT_ANNOUNCE_PAT.search(t):
            return RT_ANNOUNCEMENT
        return RT_SETTLEMENT
    if _RT_LAWSUIT_PAT.search(t):
        return RT_LAWSUIT
    return RT_NEWS


_RT_STATUS = {RT_SETTLEMENT: "Settlement", RT_ANNOUNCEMENT: "Announced / Proposed",
              RT_LAWSUIT: "Complaint Filed", RT_INVESTIGATION: "Investigation",
              RT_REGULATORY: "Regulatory Action", RT_NEWS: "News"}

# Legal-news blogs report ON settlements (announcements/rumors) rather than
# hosting claim portals, so their settlement items are Announcements unless the
# wording shows the deal is finalized/claimable.
NEWS_BLOGS = {"AboutLawsuits", "LawyersAndSettlements", "BigClassAction",
              "Lawsuit Information Center"}

# Government enforcement sources. Their releases are a mix of complaints, orders,
# merger reviews, comment requests, and (occasionally) actual monetary
# settlements. Only the last belongs in the Settlement tab; the rest are
# Regulatory so the Settlement tab stays "confirmed settlements only".
GOV_SOURCES = {"FTC press release", "SEC", "CFPB", "DOJ", "California AG",
               "Washington AG", "New York AG", "NAAG (State AGs)"}

_GOV_PROCEDURAL = re.compile(
    r"(seeks comment|comment period|petition|request for|proposes|proposed (rule|order)|"
    r"workshop|report|testimony|warns?\b|alert|guidance|acquisition|merger|divestiture|"
    r"set aside|modify (the )?order|rulemaking)", re.I)
_GOV_LAWSUIT = re.compile(
    r"(sues?\b|sued\b|files? (suit|complaint|charges|an action)|charged\b|indict\w+|"
    r"takes action against|moves to (block|stop)|sue to)", re.I)
_GOV_MONEY = re.compile(
    r"(refund|restitution|redress|disgorge\w*|returns? \$|to pay \$|pay \$[\d.,]+|"
    r"\$[\d.,]+\s*(million|billion|m\b|b\b))", re.I)
_GOV_SETTLE = re.compile(
    r"(settl\w+|consent (order|decree|judgment)|agrees? to pay|will pay|agreed to pay)", re.I)


def gov_record_type(text, amount):
    """Classify a government enforcement release. Only a settlement with consumer
    money attached counts as a confirmed Settlement; everything else is
    Regulatory (or a complaint/investigation)."""
    t = text or ""
    if _RT_INVESTIGATION_PAT.search(t):
        return RT_INVESTIGATION
    if _GOV_LAWSUIT.search(t) and not _GOV_SETTLE.search(t):
        return RT_LAWSUIT
    confirmed_money = bool(amount) or bool(_GOV_MONEY.search(t))
    if confirmed_money and _GOV_SETTLE.search(t) and not _GOV_PROCEDURAL.search(t):
        return RT_SETTLEMENT
    return RT_REGULATORY


def refine_record_type(source, record_type, text, amount=None):
    """Final say on a record's type, applied to every ingested record."""
    if source in GOV_SOURCES:
        return gov_record_type(text, amount)
    if record_type == RT_SETTLEMENT and source in NEWS_BLOGS \
            and not _RT_FINAL_PAT.search(text or ""):
        return RT_ANNOUNCEMENT
    return record_type


def slugify(name):
    s = (name or "").lower()
    s = re.sub(r"^(in re:?|in the matter of)\s+", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "matter"


_FILLER = re.compile(
    r"\b(settlement|settlements|class|action|lawsuit|litigation|data|breach|"
    r"the|of|inc|llc|lp|corp|co|company|holdings)\b", re.I)


def _dedupe_key(name):
    """A looser key that collapses near-duplicates across sources, e.g.
    '23 And Me Data Settlement' and '23Andme Data Settlement'."""
    s = (name or "").lower().replace("-", " ")
    s = re.sub(r"^(in re:?|in the matter of)\s+", "", s)
    s = _FILLER.sub(" ", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s[:40]


def first_sentence(text, limit=240):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    if not text:
        return ""
    m = re.search(r"(.+?[.!?])(\s|$)", text)
    out = (m.group(1) if m else text).strip()
    return (out[:limit].rstrip() + "…") if len(out) > limit else out


# ----------------------------------------------------------------------------
# Source connectors — each returns a list of normalized records, never raises.
# Everything the source posts is ingested; derive_record_type() tags each item
# (Settlement / Lawsuit Filed / Investigation / News & Guides) so the UI can
# filter instead of the pipeline excluding.
# ----------------------------------------------------------------------------
def _item_blocks(xml, tag="item"):
    return re.findall(r"<%s>(.*?)</%s>" % (tag, tag), xml, re.S | re.I)


def _tag(block, name):
    m = re.search(r"<%s>(.*?)</%s>" % (name, name), block, re.S | re.I)
    if not m:
        return ""
    val = m.group(1)
    val = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", val, flags=re.S)
    return html.unescape(val).strip()


def fetch_ftc():
    out = []
    xml = http_get("https://www.ftc.gov/feeds/press-release.xml").decode("utf-8", "replace")
    for block in _item_blocks(xml):
        title = _tag(block, "title")
        desc = _tag(block, "description")
        link = _tag(block, "link")
        pub = _tag(block, "pubDate")
        if not title:
            continue
        year = None
        ym = re.search(r"(20\d{2})", pub) or re.search(r"/(20\d{2})/", link)
        if ym:
            year = int(ym.group(1))
        rt = derive_record_type(title + " " + desc)
        defendant = _ftc_defendant(title)
        out.append({
            "case_name": title,
            "short_name": title[:90],
            "defendant": defendant,
            "amount": parse_amount(title + " " + desc),
            "category": classify(title + " " + desc),
            "record_type": rt,
            "year": year,
            "status": "FTC " + _RT_STATUS[rt],
            "court": "FTC",
            "court_full": "U.S. Federal Trade Commission",
            "judge": None,
            "case_number": None,
            "class_size": None,
            "fee_award": None,
            "description": first_sentence(desc) or title,
            "source": "FTC press release",
            "source_url": link,
        })
    return out


def _ftc_defendant(title):
    for marker in [" agrees to pay", " will pay", " to pay", " agreed to pay", " to settle"]:
        i = title.lower().find(marker)
        if i > 0:
            cand = title[:i].strip(" ,")
            cand = re.sub(r"^(ftc|federal trade commission)[:,]?\s*", "", cand, flags=re.I)
            if cand:
                return cand[:80]
    m = re.search(r"against ([A-Z][\w&.,'\- ]+)", title)
    if m:
        return m.group(1).strip(" ,")[:80]
    return "(see FTC release)"


def fetch_courtlistener(limit=25):
    out = []
    url = ("https://www.courtlistener.com/api/rest/v4/search/"
           "?q=%22class%20action%22%20settlement&order_by=dateFiled%20desc&type=o")
    token = os.environ.get("COURTLISTENER_TOKEN")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Authorization": ("Token " + token) if token else "",
    })
    try:
        raw = urllib.request.urlopen(req, timeout=25).read()
    except Exception:
        raw = http_get(url)
    data = json.loads(raw.decode("utf-8", "replace"))
    for r in data.get("results", [])[:limit]:
        name = r.get("caseName") or ""
        if not name:
            continue
        snippet = ""
        ops = r.get("opinions") or []
        if ops and isinstance(ops, list):
            snippet = ops[0].get("snippet") or ""
        date_filed = r.get("dateFiled") or ""
        year = int(date_filed[:4]) if re.match(r"\d{4}", date_filed) else None
        abs_url = r.get("absolute_url") or ""
        defendant = name.split(" v. ")[-1].strip() if " v. " in name else ""
        out.append({
            "case_name": name,
            "short_name": name[:90],
            "defendant": defendant or "(see docket)",
            "amount": parse_amount(snippet),
            "category": classify(name + " " + snippet),
            "year": year,
            "status": "Court Opinion",
            "court": _court_short(r.get("court") or ""),
            "court_full": r.get("court") or None,
            "judge": None,
            "case_number": r.get("docketNumber") or None,
            "class_size": None,
            "fee_award": None,
            "description": first_sentence(snippet) or ("Recent class-action settlement opinion: " + name),
            "source": "CourtListener",
            "source_url": ("https://www.courtlistener.com" + abs_url) if abs_url else None,
        })
    return out


def _court_short(full):
    if not full:
        return None
    m = re.search(r"(\d+(?:st|nd|rd|th)) Circuit", full)
    if m:
        return m.group(1) + " Cir."
    return full[:24]


def _tca_defendant(title):
    t = re.split(r"\bclass action\b", title, flags=re.I)[0]
    t = re.sub(r"\$\s?[\d.,]+\s*(million|billion|m|b)?\b", "", t, flags=re.I)
    t = re.sub(r"\bsettlement\b.*", "", t, flags=re.I).strip(" -:,")
    return t[:70] or "(see settlement notice)"


def fetch_topclassactions(limit=100):
    """Everything the Top Class Actions news feed posts — settlements, filed
    lawsuits, investigations, and roundup/guide articles — each tagged with a
    record_type and linked back to the source."""
    out = []
    xml = http_get("https://topclassactions.com/feed/").decode("utf-8", "replace")
    for block in _item_blocks(xml):
        title = _tag(block, "title")
        if not title:
            continue
        desc = _tag(block, "description")
        link = _tag(block, "link")
        pub = _tag(block, "pubDate")
        year = None
        ym = re.search(r"(20\d{2})", pub)
        if ym:
            year = int(ym.group(1))
        rt = derive_record_type(title + " " + desc)
        out.append({
            "case_name": title,
            "short_name": title[:90],
            "defendant": _tca_defendant(title),
            "amount": parse_amount(title) or parse_amount(desc),
            "category": classify(title + " " + desc),
            "record_type": rt,
            "year": year,
            "status": _RT_STATUS[rt],
            "court": None,
            "court_full": None,
            "judge": None,
            "case_number": None,
            "class_size": None,
            "fee_award": None,
            "description": first_sentence(desc) or title,
            "source": "Top Class Actions",
            "source_url": link,
        })
        if len(out) >= limit:
            break
    return out


# ---- Sitemap-based "coverage" sources -------------------------------------
# ClaimDepot and ClassAction.org don't publish RSS, but their sitemaps list
# settlement pages whose slugs encode the case and (often) the dollar amount.
# These broaden coverage; dedup means each refresh only adds what's new to you.
def _amount_from_slug(slug):
    m = re.search(r"(\d+(?:\.\d+)?)[-]?(billion|million|m|b|k)\b", slug, re.I)
    if not m:
        return None
    raw, unit = float(m.group(1)), m.group(2).lower()
    val = int(raw * _MULT[unit])
    # Slugs routinely drop the decimal point in billions ("25b" means $2.5B,
    # "267b" means $2.67B). A two-or-more-digit integer with a billions unit is
    # almost certainly such a case, and there's no reliable way to restore the
    # decimal — so reject rather than show a wrong figure. Real >$10B settlements
    # in the catalog come from the curated records, which set amounts directly.
    # Real settlements above ~$5B are essentially all in the curated records
    # (which set amounts directly). A billions-unit slug at/above that is almost
    # always a dropped-decimal artifact ("71b", "79b"), so reject it.
    if unit in ("billion", "b", "bn") and val >= 5_000_000_000:
        return None
    if val > 50_000_000_000 or val < 10000:
        return None
    return val


def _title_from_slug(slug):
    s = re.sub(r"\.php$|\.html$", "", slug)
    s = re.sub(r"\b\d+(?:\.\d+)?[-]?(billion|million|m|b|k)\b", "", s, flags=re.I)
    s = re.sub(r"[-_]+", " ", s).strip()
    s = re.sub(r"\s+", " ", s)
    # Trim the marketing tail after the word "settlement" so the case identity
    # leads (also tightens dedup against curated names).
    m = re.match(r"(.*?\bsettlement)\b", s, re.I)
    if m and len(m.group(1)) >= 8:
        s = m.group(1)
    s = re.sub(r"\s+(for|to|in|of|and|the|a|an|over)\s*$", "", s, flags=re.I).strip()
    return (s[:90].strip().title() or "Class Action Settlement")


def _defendant_from_title(title):
    t = re.split(r"\b(settlement|class action|antitrust|data breach|over |agrees|faces|alleges|reached)\b",
                 title, flags=re.I)[0].strip(" -,")
    return t[:60] or "(see source)"


def _record_from_slug(url, source_label):
    slug = url.rstrip("/").split("/")[-1]
    title = _title_from_slug(slug)
    amount = _amount_from_slug(slug)
    slug_text = slug.replace("-", " ")
    rt = derive_record_type(slug_text)
    low = url.lower()
    # A page under a news / investigations path reflects the path, not the slug.
    if _NEWS_PATH_RE.search(low):
        rt = RT_NEWS
    elif "/investigations/" in low:
        rt = RT_INVESTIGATION
    return {
        "case_name": title,
        "short_name": title,
        "defendant": _defendant_from_title(title),
        "amount": amount,
        "category": classify(slug_text),
        "record_type": rt,
        "year": None,  # sitemaps carry no date
        "status": _RT_STATUS[rt],
        "court": None, "court_full": None, "judge": None, "case_number": None,
        "class_size": None, "fee_award": None,
        "description": rt + " indexed from " + source_label +
                       (" (~" + ("$%s" % _compact_py(amount)) + ")" if amount else "") +
                       ". Open the source link for amount, parties, and claim details.",
        "source": source_label,
        "source_url": url,
    }


def _compact_py(n):
    if n is None:
        return ""
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            v = n / div
            return ("%g" % round(v, 2)) + suf
    return str(n)


def _fetch_sitemap_settlements(sitemap_url, source_label, path_re, limit=20000,
                               slug_re=None, exclude_re=None, headers=None):
    """Scan a sitemap and ingest every case page under the given paths —
    settlements, lawsuits, and investigations alike, with or without a dollar
    amount in the slug. record_type tagging happens in _record_from_slug.
    `slug_re` keeps only slugs that match; `exclude_re` drops URLs that match
    (e.g. /null placeholders or /fr/ language variants)."""
    out, seen, candidates = [], set(), 0
    xml = http_get(sitemap_url, headers=headers).decode("utf-8", "replace")
    for url in re.findall(r"<loc>(.*?)</loc>", xml, re.S | re.I):
        url = html.unescape(url.strip())
        low = url.lower()
        if not re.search(path_re, low):
            continue
        if exclude_re and re.search(exclude_re, low):
            continue
        slug = url.rstrip("/").split("/")[-1].lower()
        if not slug or slug == "null" or slug in seen:
            continue
        if slug_re and not re.search(slug_re, slug):
            continue
        seen.add(slug)
        candidates += 1
        if len(out) >= limit:
            continue  # keep counting candidates for the cap note
        out.append(_record_from_slug(url, source_label))
    if candidates > limit:
        REFRESH_NOTES.append("%s: safety cap hit — ingested %d of %d case pages "
                             "(raise the limit in server.py to take the rest)" %
                             (source_label, limit, candidates))
    return out


def fetch_claimdepot(limit=10000):
    return _fetch_sitemap_settlements(
        "https://www.claimdepot.com/sitemap.xml", "ClaimDepot",
        r"/(cases|settlements|investigations)/", limit)


def fetch_classactionorg(limit=10000):
    # classaction.org's sitemap lists ~18k URLs incl. generic info pages; keep
    # slugs that look like case/settlement/lawsuit/investigation pages.
    return _fetch_sitemap_settlements(
        "https://www.classaction.org/sitemap.xml", "ClassAction.org",
        r"/(blog|settlements)/", limit,
        slug_re=r"settle|lawsuit|sues|sued|investigat|breach|recall|refund|class[- ]action")


def fetch_openclassactions(limit=10000):
    return _fetch_sitemap_settlements(
        "https://openclassactions.com/sitemap.xml", "OpenClassActions",
        r"/(settlements|news)/", limit)


# ---- Generic RSS connector --------------------------------------------------
# Several sites (Online Legal Media network) prefix titles with the record
# type, which beats keyword inference when present.
_PREFIX_RT = [
    (re.compile(r"^\s*settlement\s*:", re.I), RT_SETTLEMENT),
    (re.compile(r"^\s*(law\s*suit|lawsuit)\s*filed\s*:", re.I), RT_LAWSUIT),
    (re.compile(r"^\s*potential\s+lawsuit\s*:", re.I), RT_INVESTIGATION),
    (re.compile(r"^\s*verdict\s*:", re.I), RT_SETTLEMENT),
]


def _fetch_rss(url, source_label, limit=120, require=None, category_hint=None,
               headers=None, default_rt=None):
    """Ingest every item from an RSS feed, tagging record_type. `require` is an
    optional regex applied to title+description — used only for broad
    government feeds so e.g. criminal sentencings don't enter a settlement DB.
    `default_rt` overrides the News fallback for enforcement-only feeds whose
    titles are bare defendant names (SEC/CFPB)."""
    out = []
    xml = http_get(url, headers=headers).decode("utf-8", "replace")
    for block in _item_blocks(xml):
        title = _tag(block, "title")
        if not title:
            continue
        desc = _tag(block, "description")
        link = _tag(block, "link")
        pub = _tag(block, "pubDate")
        if require and not require.search(title + " " + desc):
            continue
        rt = None
        clean_title = title
        for pat, mapped in _PREFIX_RT:
            if pat.search(title):
                rt = mapped
                clean_title = pat.sub("", title).strip()
                break
        if rt is None:
            rt = derive_record_type(title + " " + desc)
            if rt == RT_NEWS and default_rt:
                rt = default_rt
        year = None
        ym = re.search(r"(20\d{2})", pub)
        if ym:
            year = int(ym.group(1))
        out.append({
            "case_name": clean_title,
            "short_name": clean_title[:90],
            "defendant": _tca_defendant(clean_title),
            "amount": parse_amount(clean_title) or parse_amount(desc),
            "category": category_hint or classify(clean_title + " " + desc),
            "record_type": rt,
            "year": year,
            "status": _RT_STATUS[rt],
            "court": None, "court_full": None, "judge": None,
            "case_number": None, "class_size": None, "fee_award": None,
            "description": first_sentence(desc) or clean_title,
            "source": source_label,
            "source_url": link,
        })
        if len(out) >= limit:
            break
    return out


_CIVIL_RELEVANCE = re.compile(
    r"(settl\w+|class action|agrees? to pay|civil (penalty|judgment|suit)|"
    r"consent (order|decree|judgment)|refund|restitution|disgorgement|"
    r"to pay \$|million|billion)", re.I)


def fetch_aboutlawsuits():
    return _fetch_rss("https://www.aboutlawsuits.com/feed/", "AboutLawsuits")


def fetch_lawyersandsettlements():
    return _fetch_rss("https://www.lawyersandsettlements.com/rss.xml",
                      "LawyersAndSettlements")


def fetch_bigclassaction():
    return _fetch_rss("https://www.bigclassaction.com/rss.xml", "BigClassAction")


def fetch_lawsuitinfocenter():
    return _fetch_rss("https://www.lawsuit-information-center.com/feed",
                      "Lawsuit Information Center")


_SEC_HEADERS = {"User-Agent": "SettleSearch research contact@settlesearch.local"}


def fetch_sec_litigation():
    # SEC litigation releases (civil enforcement suits). Titles are defendant
    # names only, so default the type and skip the keyword filter.
    return _fetch_rss(
        "https://www.sec.gov/enforcement-litigation/litigation-releases/rss",
        "SEC", category_hint="Securities", headers=_SEC_HEADERS, default_rt=RT_LAWSUIT)


def fetch_sec_admin():
    # SEC administrative proceedings — mostly settled cease-and-desist orders.
    return _fetch_rss(
        "https://www.sec.gov/enforcement-litigation/administrative-proceedings/rss",
        "SEC", category_hint="Securities", headers=_SEC_HEADERS, default_rt=RT_SETTLEMENT)


def fetch_cfpb():
    return _fetch_rss("https://www.consumerfinance.gov/enforcement/actions/feed/",
                      "CFPB", default_rt=RT_SETTLEMENT)


def fetch_doj_news():
    return _fetch_rss("https://www.justice.gov/news/rss?type=press_release", "DOJ",
                      require=_CIVIL_RELEVANCE, headers={"User-Agent": BROWSER_UA})


def fetch_ca_ag():
    return _fetch_rss("https://oag.ca.gov/news/feed", "California AG",
                      require=_CIVIL_RELEVANCE)


def fetch_wa_ag():
    return _fetch_rss("https://www.atg.wa.gov/news/news-releases-rss",
                      "Washington AG", require=_CIVIL_RELEVANCE)


# ---- Additional aggregator sitemaps ----------------------------------------
def fetch_settlemate():
    return _fetch_sitemap_settlements("https://www.settlemate.io/sitemap.xml",
                                      "Settlemate", r"/settlements/")


def fetch_classactionbuddy():
    return _fetch_sitemap_settlements(
        "https://classactionbuddy.com/sitemap-settlements.xml",
        "ClassActionBuddy", r"/settlements/")


def fetch_choosecatch():
    return _fetch_sitemap_settlements("https://www.choosecatch.com/sitemap.xml",
                                      "Catch", r"/settlements/")


def fetch_dapeer():
    return _fetch_sitemap_settlements(
        "https://www.dapeer.com/sitemap.xml", "Dapeer Law",
        r"/(open-settlements|closed-settlements|class-action-in-the-news)/")


def fetch_injuryclaims():
    return _fetch_sitemap_settlements(
        "https://injuryclaims.com/sitemap.xml", "InjuryClaims",
        r"/(class-action-lawsuits|r|news)/")


def fetch_classactionrebates():
    return _fetch_sitemap_settlements(
        "https://classactionrebates.com/page-sitemap.xml", "ClassActionRebates",
        r"/settlements-1/")


def fetch_strategicclaims():
    return _fetch_sitemap_settlements(
        "https://www.strategicclaims.net/case-sitemap.xml",
        "Strategic Claims", r"/case/")


def fetch_veritaglobal():
    return _fetch_sitemap_settlements(
        "https://veritaglobal.com/mt_settlement_case-sitemap.xml", "Verita Global",
        r"/settlement-case/", exclude_re=r"/fr/")


def fetch_angeion():
    return _fetch_sitemap_settlements(
        "https://www.angeiongroup.com/sitemap.xml", "Angeion Group",
        r"/landmark-cases/")


def fetch_naag():
    return _fetch_sitemap_settlements(
        "https://www.naag.org/sitemap.xml", "NAAG (State AGs)",
        r"/multistate-case/",
        headers={"User-Agent": BROWSER_UA, "Accept": BROWSER_ACCEPT})


# ---- JSON API: claims administrators ---------------------------------------
def fetch_rg2claims(limit=2000):
    """RG/2 Claims Administration's full administered-case list (JSON), with
    court and docket number per case."""
    raw = http_get("https://www.rg2claims.com/data/newoutput.json")
    data = json.loads(raw.decode("utf-8", "replace"))
    out = []
    for r in data if isinstance(data, list) else []:
        title = (r.get("caseTitle") or "").strip()
        if not title or title.lower() == "case name":
            continue
        web = (r.get("webSite") or "").strip()
        if web and not web.lower().startswith("http"):
            web = "https://" + web
        status = (r.get("status") or "").strip().title() or "Settlement"
        out.append({
            "case_name": title, "short_name": title[:90],
            "defendant": title.split(" v. ")[-1].strip() if " v. " in title else "(see docket)",
            "amount": None, "category": classify(title),
            "record_type": RT_SETTLEMENT, "year": None, "status": status,
            "court": (r.get("court") or None), "court_full": (r.get("court") or None),
            "judge": None, "case_number": (r.get("docketNumber") or None),
            "class_size": None, "fee_award": None,
            "description": "Class-action settlement administered by RG/2 Claims (status: "
                           + status + "). Open the source link for claim details.",
            "source": "RG/2 Claims",
            "source_url": web or "https://www.rg2claims.com/cases.html",
        })
        if len(out) >= limit:
            break
    return out


# ---- HTML listing: NY Attorney General -------------------------------------
def fetch_ny_ag(limit=60):
    body = http_get("https://ag.ny.gov/press-releases",
                    headers={"User-Agent": BROWSER_UA}).decode("utf-8", "replace")
    out, seen = [], set()
    for m in re.finditer(r'href="(/press-release/(\d{4})/[^"]+)"[^>]*>(.*?)</a>',
                         body, re.S | re.I):
        path, yr, text = m.group(1), int(m.group(2)), re.sub(r"<[^>]+>", " ", m.group(3))
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        if not text or path in seen:
            continue
        seen.add(path)
        rt = derive_record_type(text)
        out.append({
            "case_name": text, "short_name": text[:90], "defendant": _tca_defendant(text),
            "amount": parse_amount(text), "category": classify(text),
            "record_type": rt, "year": yr, "status": _RT_STATUS[rt],
            "court": None, "court_full": None, "judge": None, "case_number": None,
            "class_size": None, "fee_award": None,
            "description": first_sentence(text) or text,
            "source": "New York AG", "source_url": "https://ag.ny.gov" + path,
        })
        if len(out) >= limit:
            break
    return out


# Default live sources. Everything the site posts is ingested and tagged by
# record_type so the UI can filter (Settlement / Lawsuit Filed / Investigation /
# News & Guides). fetch_courtlistener() stays OFF by default (opinions about
# class actions, not settlements with amounts) but remains available in the code.
SOURCES = [
    # Fresh, dated headlines
    ("FTC", fetch_ftc),
    ("Top Class Actions", fetch_topclassactions),
    ("AboutLawsuits", fetch_aboutlawsuits),
    ("LawyersAndSettlements", fetch_lawyersandsettlements),
    ("BigClassAction", fetch_bigclassaction),
    ("Lawsuit Information Center", fetch_lawsuitinfocenter),
    # Aggregator catalogs (sitemaps)
    ("ClaimDepot", fetch_claimdepot),
    ("ClassAction.org", fetch_classactionorg),
    ("OpenClassActions", fetch_openclassactions),
    ("ClassActionBuddy", fetch_classactionbuddy),
    ("Dapeer Law", fetch_dapeer),
    ("InjuryClaims", fetch_injuryclaims),
    ("Catch", fetch_choosecatch),
    ("Settlemate", fetch_settlemate),
    ("ClassActionRebates", fetch_classactionrebates),
    # Claims administrators
    ("RG/2 Claims", fetch_rg2claims),
    ("Strategic Claims", fetch_strategicclaims),
    ("Verita Global", fetch_veritaglobal),
    ("Angeion Group", fetch_angeion),
    # Government / regulators
    ("SEC Litigation", fetch_sec_litigation),
    ("SEC Admin", fetch_sec_admin),
    ("CFPB", fetch_cfpb),
    ("DOJ", fetch_doj_news),
    ("California AG", fetch_ca_ag),
    ("Washington AG", fetch_wa_ag),
    ("NY AG", fetch_ny_ag),
    ("NAAG", fetch_naag),
]


# ----------------------------------------------------------------------------
# Store load / save
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# Durable store (SQLite). Each record is one row keyed by id, with the full
# record as a JSON blob plus a few indexed columns. Lives at DB_PATH — put that
# on a persistent disk in production and every refresh is saved permanently.
# ----------------------------------------------------------------------------
_DB_LOCK = threading.Lock()
_API_CACHE = {"json": None, "gzip": None, "count": 0, "last_updated": None}


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_store():
    """Create the schema and, on first run (empty DB), seed it from the bundled
    settlements.json so the live site ships with the full baseline catalog."""
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with _DB_LOCK, _connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS settlements (
            id TEXT PRIMARY KEY, record_type TEXT, year INTEGER, amount INTEGER,
            source TEXT, slug TEXT, dkey TEXT, data TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_slug ON settlements(slug)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_dkey ON settlements(dkey)")
        c.execute("""CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)""")
        (count,) = c.execute("SELECT COUNT(*) FROM settlements").fetchone()
    if count == 0:
        seed = STORE if os.path.exists(STORE) else (SEED if os.path.exists(SEED) else None)
        if seed:
            with open(seed, encoding="utf-8") as f:
                records = json.load(f)
            _backfill_record_type(records)
            _insert_records(records)
            print("Seeded store with %d records from %s" % (len(records), os.path.basename(seed)))
    _invalidate_cache()


def _row_tuple(r):
    nm = r.get("short_name") or r.get("case_name")
    rt = r.get("record_type") or RT_SETTLEMENT
    return (r.get("id"), rt, r.get("year"), r.get("amount"), r.get("source"),
            slugify(nm), rt + "|" + _dedupe_key(nm),
            json.dumps({k: r.get(k) for k in FIELDS}, ensure_ascii=False))


def _insert_records(records):
    with _DB_LOCK, _connect() as c:
        c.executemany(
            "INSERT OR IGNORE INTO settlements "
            "(id, record_type, year, amount, source, slug, dkey, data) "
            "VALUES (?,?,?,?,?,?,?,?)", [_row_tuple(r) for r in records])


def append_records(records):
    """Persist new records (durable). Used by refresh — only the new ones."""
    if records:
        _insert_records(records)
    _invalidate_cache()


def load_store():
    with _connect() as c:
        rows = c.execute("SELECT data FROM settlements ORDER BY rowid").fetchall()
    return [json.loads(r[0]) for r in rows]


def store_count():
    with _connect() as c:
        return c.execute("SELECT COUNT(*) FROM settlements").fetchone()[0]


def known_keys():
    """All dedup keys already in the store, without deserializing every blob."""
    with _connect() as c:
        rows = c.execute("SELECT id, slug, dkey FROM settlements").fetchall()
    keys = set()
    for _id, slug, dkey in rows:
        keys.add((_id or "").lower()); keys.add(slug); keys.add(dkey)
    return keys


def read_meta():
    with _connect() as c:
        row = c.execute("SELECT v FROM meta WHERE k='last_updated'").fetchone()
    return {"last_updated": row[0] if row else None}


def write_meta(m):
    with _DB_LOCK, _connect() as c:
        c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('last_updated', ?)",
                  (m.get("last_updated"),))


def _invalidate_cache():
    _API_CACHE["json"] = None
    _API_CACHE["gzip"] = None


def api_settlements_body(want_gzip):
    """Return (bytes, gzipped?) for GET /api/settlements, cached until the store
    changes so we don't re-serialize 10k+ rows on every page load."""
    if _API_CACHE["json"] is None:
        payload = {"settlements": load_store(), "last_updated": read_meta()["last_updated"]}
        raw = json.dumps(payload).encode("utf-8")
        _API_CACHE["json"] = raw
        _API_CACHE["gzip"] = gzip.compress(raw, 6)
    if want_gzip:
        return _API_CACHE["gzip"], True
    return _API_CACHE["json"], False


def export_data_js():
    """Write data.js (offline fallback / static-deploy export) from the DB."""
    records = load_store()
    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write("/* SettleSearch dataset — exported by server.py. */\n")
        f.write("window.SETTLEMENTS = ")
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write(";\n")
    return len(records)


# ----------------------------------------------------------------------------
# Enrichment — fetch each settlement page and pull the dollar amount + year out
# of the page's own summary (meta description / H1), which is case-specific and
# clean. We never guess: if the figure isn't reliably present, the field stays
# blank and the source link lets the user see it. Many claims-administrator
# pages are JavaScript-rendered (no readable amount), so coverage is partial.
# ----------------------------------------------------------------------------
import concurrent.futures as _cf

_META_DESC = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.S | re.I)
_OG_DESC = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', re.S | re.I)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_PUB_YEAR = re.compile(r'(?:article:published_time|og:updated_time)["\'][^>]+content=["\'](\d{4})', re.I)
_JS_JUNK = re.compile(r"(var |function|=>|H1_MAP|\{)")


def _strip(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _enrich_one(rec):
    """Return {amount?, year?} extracted from the record's page, or {}."""
    url = (rec.get("source_url") or "").strip()
    if not url.startswith("http") or "cases.html" in url:
        return {}
    try:
        page = http_get(url, timeout=15,
                        headers={"User-Agent": BROWSER_UA, "Accept": "text/html"}).decode("utf-8", "replace")
    except Exception:
        return {}
    m = _META_DESC.search(page) or _OG_DESC.search(page)
    desc = html.unescape(_strip(m.group(1) if m else ""))
    h1 = _strip((_H1.search(page) or [None, ""])[1] if _H1.search(page) else "")
    title = _strip((_TITLE.search(page) or [None, ""])[1] if _TITLE.search(page) else "")
    head = h1 if h1 and not _JS_JUNK.search(h1) else ""
    head = (head + " " + title).strip()
    out = {}
    if rec.get("amount") is None:
        # Description first (it's a clean, case-specific summary), then headline.
        a = parse_amount(desc) or parse_amount(head)
        if a is not None:
            out["amount"] = a
    if rec.get("year") is None:
        sy = re.search(r"-(20[0-2]\d)(?:[-/]|$)", url)
        py = _PUB_YEAR.search(page)
        y = int(sy.group(1)) if sy else (int(py.group(1)) if py else None)
        if y and 2005 <= y <= 2026:
            out["year"] = y
    return out


def enrich_missing(limit=1500, workers=6):
    """Fill missing amount/year for up to `limit` not-yet-attempted records
    (Settlement first). Each record is attempted once (marked enriched_at) so
    un-fillable / JS-rendered pages aren't re-fetched on every run."""
    with _connect() as c:
        rows = c.execute(
            "SELECT id, data FROM settlements "
            "WHERE (amount IS NULL OR year IS NULL) "
            "AND data LIKE '%\"source_url\": \"http%' "
            "AND data NOT LIKE '%\"enriched_at\": \"%' "
            "ORDER BY (record_type='Settlement') DESC, rowid LIMIT ?", (limit,)).fetchall()
    todo = [(rid, json.loads(blob)) for rid, blob in rows]
    today = datetime.now(timezone.utc).date().isoformat()

    def work(item):
        rid, rec = item
        got = _enrich_one(rec)        # {} if nothing reliable found
        rec.update(got)
        rec["enriched_at"] = today    # mark attempted either way
        return (rid, rec, got)

    results = []
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(work, todo):
            results.append(res)

    n_amt = n_yr = 0
    with _DB_LOCK, _connect() as c:
        for rid, rec, got in results:
            if "amount" in got:
                n_amt += 1
            if "year" in got:
                n_yr += 1
            c.execute("UPDATE settlements SET amount=?, year=?, data=? WHERE id=?",
                      (rec.get("amount"), rec.get("year"),
                       json.dumps(rec, ensure_ascii=False), rid))
    _invalidate_cache()
    return {"scanned": len(todo), "amounts_filled": n_amt, "years_filled": n_yr}


# ----------------------------------------------------------------------------
# Refresh — pull, dedup, merge, persist
# ----------------------------------------------------------------------------
_CURATED_STATUSES = {"final approval", "global settlement", "preliminary",
                     "pending", "verdict", "settlement", "ftc settlement"}


def _backfill_record_type(records):
    """Ensure every stored record carries record_type (older stores predate it)."""
    changed = False
    for r in records:
        if r.get("record_type"):
            continue
        rt = derive_record_type((r.get("short_name") or "") + " " +
                                (r.get("description") or ""))
        # Curated/earlier records all passed settlement gates; don't let the
        # News-default misfile e.g. "Equifax Data Breach".
        if rt == RT_NEWS and (r.get("status") or "").lower() in _CURATED_STATUSES:
            rt = RT_SETTLEMENT
        r["record_type"] = rt
        changed = True
    return changed


def refresh():
    del REFRESH_NOTES[:]
    known = known_keys()

    def _keys(nm, rt):
        return (slugify(nm), (rt or RT_SETTLEMENT) + "|" + _dedupe_key(nm))

    per_source, errors, candidates = {}, [], []
    for label, fn in SOURCES:
        try:
            got = fn()
            per_source[label] = len(got)
            candidates.extend(got)
        except Exception as e:
            per_source[label] = 0
            errors.append("%s: %s" % (label, e))

    today = datetime.now(timezone.utc).date().isoformat()
    added = []
    for c in candidates:
        nm = c.get("short_name") or c.get("case_name")
        # Final type pass: route govt enforcement → Regulatory, news-blog
        # "settlement" reports → Announcement, etc.
        refined = refine_record_type(c.get("source"), c.get("record_type"),
                                     nm + " " + (c.get("description") or ""),
                                     c.get("amount"))
        if refined != c.get("record_type"):
            c["record_type"] = refined
            c["status"] = _RT_STATUS[refined]
        slug, dkey = _keys(nm, c.get("record_type"))
        if slug in known or dkey in known:
            continue
        known.add(slug)
        known.add(dkey)
        new_id = (c.get("source", "src").split()[0].lower() + "-" + slug)[:72]
        rec = {k: c.get(k) for k in FIELDS}
        rec["id"] = new_id
        rec["date_added"] = today
        added.append(rec)

    append_records(added)  # durable: persists the new rows to SQLite
    stamp = datetime.now(timezone.utc).isoformat()
    write_meta({"last_updated": stamp})
    _invalidate_cache()
    by_type = {}
    for r in added:
        by_type[r.get("record_type") or "?"] = by_type.get(r.get("record_type") or "?", 0) + 1
    return {
        "ok": True,
        "added": len(added),
        "total": store_count(),
        "last_updated": stamp,
        "sources": per_source,
        "by_type": by_type,
        "notes": list(REFRESH_NOTES),
        "errors": errors,
        "new_items": [{"short_name": r["short_name"], "amount": r["amount"],
                       "category": r["category"], "record_type": r["record_type"],
                       "source": r["source"], "source_url": r["source_url"]}
                      for r in added[:25]],
    }


# ----------------------------------------------------------------------------
# HTTP handler
# ----------------------------------------------------------------------------
_REFRESH_STATE = {"at": None}


def refresh_guarded():
    """Wrap refresh() with a cooldown. On a public site the Refresh button is
    reachable by anyone (and bots), so cap how often an actual pull runs. Within
    the cooldown window the call returns immediately with a friendly note instead
    of re-hitting 25 external sites. Set REFRESH_COOLDOWN=0 to disable."""
    cooldown = int(os.environ.get("REFRESH_COOLDOWN", "60"))
    now = datetime.now(timezone.utc)
    last = _REFRESH_STATE["at"]
    if last is not None and cooldown > 0:
        elapsed = (now - last).total_seconds()
        if elapsed < cooldown:
            meta = read_meta()
            return {
                "ok": True, "added": 0, "total": store_count(),
                "last_updated": meta.get("last_updated"),
                "sources": {}, "by_type": {}, "errors": [], "new_items": [],
                "notes": ["Just refreshed %ds ago — try again in %ds."
                          % (int(elapsed), int(cooldown - elapsed))],
            }
    result = refresh()
    _REFRESH_STATE["at"] = now
    return result


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/settlements":
            want_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
            body, gzipped = api_settlements_body(want_gzip)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            if gzipped:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/config":
            return self._json({"site_name": SITE_NAME})
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] == "/api/refresh":
            try:
                return self._json(refresh_guarded())
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)
        self.send_error(404)

    def log_message(self, fmt, *args):
        # Keep the console quiet for static assets, but never let logging raise
        # (log_error passes an int status code as args[0], not a string).
        try:
            line = args[0] if args else ""
            if isinstance(line, str) and "/api/" in line:
                super().log_message(fmt, *args)
        except Exception:
            pass

    def do_HEAD(self):
        return super().do_HEAD()

    def end_headers(self):
        # Always serve fresh assets in dev so edits to app.js/styles.css/data.js
        # show on reload (no stale-cache confusion). Static hosts set their own
        # caching in production, where server.py isn't used.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


def _auto_refresh_loop(hours):
    """Background scheduler: pull fresh data every `hours` so the site stays
    current with no one clicking. Runs in a daemon thread."""
    interval = max(0.25, hours) * 3600
    while True:
        time.sleep(interval)
        try:
            r = refresh()
            _REFRESH_STATE["at"] = datetime.now(timezone.utc)
            print("[auto-refresh] added %d, total %d" % (r["added"], r["total"]))
        except Exception as e:
            print("[auto-refresh] failed: %s" % e)


def main():
    init_store()  # create schema + seed from baseline on first run

    if "--refresh-once" in sys.argv:
        print(json.dumps(refresh(), indent=2))
        return
    if "--export" in sys.argv:
        # Write both the offline fallback (data.js) and the git-committed store
        # (settlements.json) from the DB. Used by the free GitHub Actions path,
        # where settlements.json in the repo is the durable, growing dataset.
        records = load_store()
        with open(STORE, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        export_data_js()
        print("Exported %d records to settlements.json and data.js" % len(records))
        return
    if "--enrich" in sys.argv:
        limit = int(os.environ.get("ENRICH_LIMIT", "1500"))
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        print(json.dumps(enrich_missing(limit), indent=2))
        return

    # Hosting platforms (Render, Railway, Fly, etc.) inject the port via $PORT and
    # require binding to all interfaces. Locally we default to localhost-only.
    env_port = os.environ.get("PORT")
    port = int(env_port) if env_port else 8765
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    host = os.environ.get("HOST") or ("0.0.0.0" if env_port else "127.0.0.1")

    # Auto-refresh scheduler (set AUTO_REFRESH_HOURS=0 to disable).
    hours = float(os.environ.get("AUTO_REFRESH_HOURS", "6"))
    if hours > 0:
        threading.Thread(target=_auto_refresh_loop, args=(hours,), daemon=True).start()
        print("Auto-refresh every %g h" % hours)

    httpd = ThreadingHTTPServer((host, port), Handler)
    where = "http://localhost:%d" % port if host == "127.0.0.1" else "%s:%d" % (host, port)
    print("SettleSearch running on %s  (%d records)" % (where, store_count()))
    print("Live refresh endpoint: POST /api/refresh")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
