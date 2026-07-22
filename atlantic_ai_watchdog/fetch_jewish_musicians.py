#!/usr/bin/env python3
"""
Fetch notable Jewish musicians from Wikidata (public figures whose Wikidata record
lists ethnic group = Jewish people (P172=Q7325) OR religion = Judaism (P140=Q9268)),
who are singers/musicians/bands and have a MusicBrainz id, ranked by notability
(sitelink count). Output: name,mbid.

NOTE: This is based on public Wikidata classifications of public figures and is
necessarily incomplete and approximate — not every Jewish musician is tagged, and
tags can be imprecise. For outreach segmentation only; verify individually.
"""
import csv, json, sys, urllib.parse, urllib.request

UA = "AIWatchdogScreener/1.0 (research; contact: dovidysamson@gmail.com)"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
OUT = sys.argv[2] if len(sys.argv) > 2 else "jewish_musicians.csv"

QUERY = f"""
SELECT DISTINCT ?artistLabel ?mbid (MAX(?sl) AS ?sitelinks) WHERE {{
  ?artist wdt:P434 ?mbid .
  ?artist wikibase:sitelinks ?sl .
  {{ ?artist wdt:P172 wd:Q7325 }} UNION {{ ?artist wdt:P140 wd:Q9268 }}
  {{ ?artist wdt:P106 wd:Q177220 }} UNION {{ ?artist wdt:P106 wd:Q639669 }}
  UNION {{ ?artist wdt:P106 wd:Q753110 }} UNION {{ ?artist wdt:P31 wd:Q215380 }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
GROUP BY ?artistLabel ?mbid
ORDER BY DESC(?sitelinks)
LIMIT {LIMIT}
"""
# Q177220 singer, Q639669 musician, Q753110 songwriter, Q215380 musical group

url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": QUERY, "format": "json"})
req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
with urllib.request.urlopen(req, timeout=120) as r:
    data = json.loads(r.read().decode("utf-8"))

seen, rows = set(), []
for b in data["results"]["bindings"]:
    name = b["artistLabel"]["value"].strip(); mbid = b["mbid"]["value"].strip()
    if not name or name.startswith("Q") or mbid in seen:
        continue
    seen.add(mbid); rows.append((name, mbid))
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["name", "mbid"])
    for n, m in rows:
        w.writerow([n, m])
print(f"wrote {len(rows)} Jewish musicians -> {OUT}")
print("top 15:", ", ".join(n for n, _ in rows[:15]))
