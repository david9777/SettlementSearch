#!/usr/bin/env python3
"""
Fetch a ranked list of top/most-notable music artists from Wikidata, with their
MusicBrainz MBIDs (which the AI Watchdog tool uses as its creator id, so matches
are exact). Notability proxy = number of Wikipedia sitelinks.

Output CSV: name,mbid   (ready for: python scrape.py --mode music --input <this>)
"""
import csv, json, sys, time, urllib.parse, urllib.request

UA = "AIWatchdogScreener/1.0 (research; contact: dovidysamson@gmail.com)"
ENDPOINT = "https://query.wikidata.org/sparql"

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
OUT = sys.argv[2] if len(sys.argv) > 2 else "artists_top.csv"

# singers (Q177220), musicians (Q639669), or musical groups/bands (Q215380/Q2088357),
# that have a MusicBrainz artist id, ranked by sitelink count.
QUERY = f"""
SELECT ?artistLabel ?mbid ?sitelinks WHERE {{
  ?artist wdt:P434 ?mbid .
  ?artist wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks >= 8)
  {{ ?artist wdt:P106 wd:Q177220 }} UNION
  {{ ?artist wdt:P106 wd:Q639669 }} UNION
  {{ ?artist wdt:P31  wd:Q215380 }} UNION
  {{ ?artist wdt:P31  wd:Q2088357 }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
ORDER BY DESC(?sitelinks)
LIMIT {LIMIT}
"""

def run():
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": QUERY, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    rows = data["results"]["bindings"]
    seen, out = set(), []
    for b in rows:
        name = b["artistLabel"]["value"].strip()
        mbid = b["mbid"]["value"].strip()
        if not name or name.startswith("Q") or mbid in seen:
            continue
        seen.add(mbid)
        out.append((name, mbid, int(b["sitelinks"]["value"])))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "mbid"])
        for name, mbid, _ in out:
            w.writerow([name, mbid])
    print(f"wrote {len(out)} artists to {OUT}")
    print("top 15:", ", ".join(n for n, _, _ in out[:15]))

if __name__ == "__main__":
    run()
