#!/usr/bin/env python3
"""
Atlantic "AI Watchdog" dataset screener — music (singers) and video (YouTube creators).

For each name in an input list, query The Atlantic's AI Watchdog tool and record
which datasets the creator appears in and how many of their works are in each.
Anyone appearing in a dataset classified as "USED_BY" (its "Learn more" page says
the dataset "has been used by" an AI company to train/experiment) is flagged as a
target to investigate manually. A separate flag marks "downloaded-only" datasets.

Which datasets exist, and whether each is USED_BY vs DOWNLOADED_ONLY, is a fixed
property of the dataset (stated on its article page). Classify once in
datasets_config.py; this script reuses it for every name.

API (public JSON, works headlessly — no browser, no auth):
  GET  /api/autocomplete?q=<name>&dataset=<music|video>
       -> {"suggestions":[{"name","id?","doc_count"}]}
       music: `id` is the MusicBrainz MBID. video: no id.
  POST /api/datasets/grouped
       body: {"searchTerm","filters":[{"field":"dataset","values":[...]}],
              "resultsPerDataset":N[, "creatorId":<id>]}
       -> {"datasetGroups":[{"name","totalCount",...}],"totalResults":N}
       music: pass creatorId (the MBID) to isolate the exact artist.
       video: creatorId omitted; the exact creator name isolates the channel.

robots.txt allows automated access with Crawl-delay: 1 -> default ~1.2s/name.
This does targeted lookups, not a bulk download of the datasets themselves.

Usage:
  python scrape.py --mode music --input artists.csv  --output music_results.csv \
                   --flagged-output music_flagged.csv
  python scrape.py --mode video --input channels.csv --output video_results.csv \
                   --flagged-output video_flagged.csv

Input CSV header:
  music: name[,mbid]   (provide mbid when known -> exact match; names are ambiguous)
  video: name          (exact YouTube channel name)

Re-running with the same --output resumes (skips already-processed names).
"""
from __future__ import annotations
import argparse, csv, json, os, sys, time, unicodedata
import urllib.error, urllib.parse, urllib.request

from datasets_config import MODES

BASE = "https://ai-watchdog.embedded.theatlantic.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split()).casefold()


def http_json(url, body=None, retries=4, timeout=30):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers,
                                         method="POST" if body is not None else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError) as e:
            last = e
            time.sleep(2 * (2 ** attempt))
    raise RuntimeError(f"request failed after {retries} tries: {url}: {last}")


def autocomplete(name, mode):
    q = urllib.parse.urlencode({"q": name, "dataset": mode})
    return http_json(f"{BASE}/api/autocomplete?{q}").get("suggestions", [])


def grouped(name, mode, datasets, creator_id=None):
    body = {"searchTerm": name,
            "filters": [{"field": "dataset", "values": datasets}],
            "resultsPerDataset": 1}
    if creator_id:
        body["creatorId"] = creator_id
    return http_json(f"{BASE}/api/datasets/grouped", body=body)


def pick_match(name, mbid, suggestions):
    """Music: match by MBID if available, else exact normalized name."""
    if mbid:
        for s in suggestions:
            if s.get("id") == mbid:
                return s
    target = norm(name)
    exact = [s for s in suggestions if norm(s.get("name", "")) == target]
    return max(exact, key=lambda s: s.get("doc_count", 0)) if exact else None


def classify(present, status):
    if not present:
        return "NONE"
    st = {status.get(d, "UNKNOWN") for d in present}
    if "USED_BY" in st:            # trained/experimented by a named AI company
        return "USED_BY"
    if "DOWNLOADED_ONLY" in st:    # downloaded/popular, no company named
        return "DOWNLOADED_ONLY"
    if "ASSEMBLED_ONLY" in st:     # in a training set, but no usage/download claim
        return "PRESENT"
    return "PRESENT_UNCLASSIFIED"  # dataset(s) not yet classified


def load_done(path):
    done = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add(row.get("query_name", ""))
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=list(MODES))
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--delay", type=float, default=1.2)
    ap.add_argument("--flagged-output", default=None,
                    help="CSV of only USED_BY-flagged names")
    args = ap.parse_args()

    cfg = MODES[args.mode]
    datasets = cfg["datasets"]
    status = cfg["status"]
    needs_id = cfg["needs_creator_id"]
    used_by = cfg.get("used_by", {})

    fields = (["query_name", "matched_name", "creator_id", "total_results"]
              + [f"count__{d}" for d in datasets]
              + ["present_datasets", "used_by_datasets", "used_by_companies", "flag"])

    with open(args.input, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("name") or "").strip()]

    done = load_done(args.output)
    new = not os.path.exists(args.output)
    out = open(args.output, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(out, fieldnames=fields)
    if new:
        w.writeheader()

    total, flagged = len(rows), 0
    for i, row in enumerate(rows, 1):
        name = row["name"].strip()
        mbid = (row.get("mbid") or "").strip() or None
        if name in done:
            continue
        try:
            rec = {k: "" for k in fields}
            rec["query_name"] = name
            creator_id, matched, g = None, name, None

            if needs_id:
                # Fast path: we already have the MBID -> call grouped directly,
                # skipping autocomplete. Most notable artists are present, so this
                # is 1 request/artist instead of 2.
                if mbid:
                    g_try = grouped(name, args.mode, datasets, creator_id=mbid)
                    if g_try.get("totalResults", 0) > 0:
                        creator_id, matched, g = mbid, name, g_try
                    else:
                        time.sleep(args.delay)
                # No MBID, or MBID returned nothing -> resolve by name.
                if g is None:
                    sugg = autocomplete(name, args.mode)
                    m = pick_match(name, mbid, sugg)
                    time.sleep(args.delay)
                    if not m or m.get("doc_count", 0) == 0:
                        rec["matched_name"] = m.get("name", "") if m else ""
                        rec["creator_id"] = m.get("id", "") if m else ""
                        rec["total_results"] = m.get("doc_count", 0) if m else 0
                        rec["flag"] = "NONE"
                        w.writerow(rec); out.flush()
                        print(f"[{i}/{total}] {name!r} -> NONE", flush=True)
                        continue
                    creator_id, matched = m["id"], m["name"]

            if g is None:
                g = grouped(matched, args.mode, datasets, creator_id)
            present = {grp["name"]: grp.get("totalCount", 0)
                       for grp in g.get("datasetGroups", [])
                       if grp.get("totalCount", 0) > 0}
            rec["matched_name"] = matched
            rec["creator_id"] = creator_id or ""
            rec["total_results"] = g.get("totalResults", 0)
            for d in datasets:
                rec[f"count__{d}"] = present.get(d, 0)
            rec["present_datasets"] = ";".join(sorted(present))
            ub = [d for d in present if status.get(d) == "USED_BY"]
            rec["used_by_datasets"] = ";".join(sorted(ub))
            companies = sorted({c for d in ub for c in used_by.get(d, [])})
            rec["used_by_companies"] = ";".join(companies)
            rec["flag"] = classify(present, status)
            w.writerow(rec); out.flush()
            if rec["flag"] == "USED_BY":
                flagged += 1
            print(f"[{i}/{total}] {name!r} -> {rec['flag']} "
                  f"[{rec['used_by_datasets'] or '-'}] ({rec['total_results']})",
                  flush=True)
        except Exception as e:
            print(f"[{i}/{total}] {name!r} ERROR: {e}", file=sys.stderr, flush=True)
        time.sleep(args.delay)
    out.close()

    if args.flagged_output:
        with open(args.output, newline="", encoding="utf-8") as f, \
             open(args.flagged_output, "w", newline="", encoding="utf-8") as g:
            r = csv.DictReader(f)
            fw = csv.DictWriter(g, fieldnames=r.fieldnames)
            fw.writeheader()
            for row in r:
                if row.get("flag") == "USED_BY":
                    fw.writerow(row)

    unknowns = [d for d, s in status.items() if s == "UNKNOWN"]
    print(f"\nDone [{args.mode}]. USED_BY-flagged this run: {flagged}.")
    if unknowns:
        print(f"NOTE: {len(unknowns)} dataset(s) still UNKNOWN in datasets_config.py "
              f"-> those appearances show as PRESENT_UNCLASSIFIED: {', '.join(unknowns)}")


if __name__ == "__main__":
    main()
