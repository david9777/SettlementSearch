#!/usr/bin/env python3
"""
Recompute flags on an existing results CSV using the CURRENT datasets_config.py,
without re-hitting the API. Use this after you update a dataset's status/used_by
in datasets_config.py — the scrape already stored `present_datasets`, so flags can
be re-derived in seconds.

Usage:
  python reclassify.py --mode music --results music_top_results.csv \
                       --out music_top_results.reclassified.csv \
                       --flagged-output music_top_flagged.csv
"""
import argparse, csv
from datasets_config import MODES


def classify(present, status):
    if not present:
        return "NONE"
    st = {status.get(d, "UNKNOWN") for d in present}
    if "USED_BY" in st:
        return "USED_BY"
    if "DOWNLOADED_ONLY" in st:
        return "DOWNLOADED_ONLY"
    if "ASSEMBLED_ONLY" in st:
        return "PRESENT"
    return "PRESENT_UNCLASSIFIED"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=list(MODES))
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--flagged-output", default=None)
    args = ap.parse_args()

    cfg = MODES[args.mode]
    status, used_by = cfg["status"], cfg.get("used_by", {})

    with open(args.results, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fields = rows[0].keys() if rows else []

    counts = {}
    for row in rows:
        present = [d for d in (row.get("present_datasets") or "").split(";") if d]
        ub = [d for d in present if status.get(d) == "USED_BY"]
        row["used_by_datasets"] = ";".join(sorted(ub))
        row["used_by_companies"] = ";".join(sorted({c for d in ub for c in used_by.get(d, [])}))
        row["flag"] = classify(present, status) if present else (row.get("flag") or "NONE")
        counts[row["flag"]] = counts.get(row["flag"], 0) + 1

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fields))
        w.writeheader(); w.writerows(rows)

    if args.flagged_output:
        with open(args.flagged_output, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(fields))
            w.writeheader()
            for row in rows:
                if row.get("flag") == "USED_BY":
                    w.writerow(row)

    print("reclassified", len(rows), "rows:", dict(sorted(counts.items())))


if __name__ == "__main__":
    main()
