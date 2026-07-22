#!/usr/bin/env python3
"""
Fetch a ranked list of top YouTube creators from Wikidata (entities with a YouTube
channel id, ranked by Wikipedia-sitelink count as a notability proxy). The video
tool matches on the creator's display name, so we output the label.

Output CSV: name   (ready for: python scrape.py --mode video --input <this>)
Note: some Wikidata labels are the person's legal name rather than the channel
name, which will simply not match (reported NONE) — acceptable for a first pass.
"""
import csv, json, sys, urllib.parse, urllib.request

UA = "AIWatchdogScreener/1.0 (research; contact: dovidysamson@gmail.com)"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
OUT = sys.argv[2] if len(sys.argv) > 2 else "channels_top.csv"

QUERY = f"""
SELECT DISTINCT ?label ?sitelinks WHERE {{
  ?item wdt:P2397 ?ytid .                 # has a YouTube channel id
  ?item wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks >= 5)
  ?item rdfs:label ?label . FILTER(LANG(?label)="en")
}}
ORDER BY DESC(?sitelinks)
LIMIT {LIMIT}
"""

url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": QUERY, "format": "json"})
req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
with urllib.request.urlopen(req, timeout=120) as r:
    data = json.loads(r.read().decode("utf-8"))

seen, rows = set(), []
for b in data["results"]["bindings"]:
    name = b["label"]["value"].strip()
    if name and name.lower() not in seen:
        seen.add(name.lower()); rows.append(name)

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["name"])
    for n in rows:
        w.writerow([n])
print(f"wrote {len(rows)} channels to {OUT}")
print("top 15:", ", ".join(rows[:15]))
