#!/usr/bin/env python3
"""
Harvest the COMPLETE artist list of a dataset by paginating /api/datasets/expand.
Default target: free-music-archive (the one music dataset marked USED_BY — used to
train models by Google and Stability AI). Aggregates per-artist track counts.

Output CSV: name,mbid,fma_track_count   (sorted by count desc)
This is the real "used by" music target list (indie/Creative-Commons artists).

Usage:
  python harvest_fma.py                       # free-music-archive -> fma_artists.csv
  python harvest_fma.py <dataset-slug> <out.csv> <page-size>
"""
import csv, json, sys, time
import urllib.error, urllib.request

BASE = "https://ai-watchdog.embedded.theatlantic.com/api/datasets/expand"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

DATASET = sys.argv[1] if len(sys.argv) > 1 else "free-music-archive"
OUT = sys.argv[2] if len(sys.argv) > 2 else "fma_artists.csv"
SIZE = int(sys.argv[3]) if len(sys.argv) > 3 else 500
MAX_PAGES = int(sys.argv[4]) if len(sys.argv) > 4 else 0   # 0 = no cap
DELAY = 0.7


def post(body, retries=4):
    data = json.dumps(body).encode("utf-8")
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Content-Type": "application/json"}
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(BASE, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError) as e:
            last = e
            time.sleep(2 * (2 ** attempt))
    raise RuntimeError(f"expand failed: {last}")


def main():
    def checkpoint():
        rws = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["name", "mbid", "fma_track_count"])
            for (name, mbid), n in rws:
                w.writerow([name, mbid, n])

    counts = {}       # (name, mbid) -> track count
    search_after, pit = None, None
    page, seen = 0, 0
    while True:
        body = {"dataset": DATASET, "searchTerm": "",
                "filters": [{"field": "dataset", "values": [DATASET]}],
                "searchAfter": search_after, "size": SIZE, "pageIndex": page, "gen": 0}
        if pit:
            body["pitId"] = pit
        d = post(body)
        results = d.get("results", [])
        if not results:
            break
        for r in results:
            for c in (r.get("structured_creators") or []):
                # accept any creator role (music: "artist"; video: "uploader")
                key = (c.get("name", "").strip(), c.get("id", "") or "")
                if not key[0]:
                    continue
                counts[key] = counts.get(key, 0) + 1
            seen += 1
        total = d.get("totalCount")
        search_after = d.get("searchAfter")
        pit = d.get("pitId") or pit
        page += 1
        print(f"page {page}: +{len(results)} tracks (seen {seen}"
              + (f"/{total}" if total else "") + f"), {len(counts)} artists", flush=True)
        if page % 200 == 0:
            checkpoint()
        if not d.get("hasMore") or not search_after:
            break
        if MAX_PAGES and page >= MAX_PAGES:
            print(f"NOTE: stopped at page cap {MAX_PAGES} ({seen} tracks seen); "
                  f"dataset has more — this is a partial sample, not the full list.")
            break
        time.sleep(DELAY)

    rows = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "mbid", "fma_track_count"])
        for (name, mbid), n in rows:
            w.writerow([name, mbid, n])
    print(f"\nDone. {seen} tracks -> {len(rows)} unique artists -> {OUT}")
    print("Top 20:", ", ".join(f"{n}({c})" for (n, _), c in rows[:20]))


if __name__ == "__main__":
    main()
