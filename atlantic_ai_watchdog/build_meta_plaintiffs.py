#!/usr/bin/env python3
"""
Aggregate harvested authors from the datasets Meta used to train Llama
(Books3 + LibGen shadow libraries) into a single ranked potential-plaintiff list.
Rank by total number of books in the Meta-used datasets (claim strength).

Output: meta_plaintiffs.csv  and  Meta_Plaintiffs.xlsx
"""
import csv, os, re, sys
import unicodedata

# Source files: default to the preserved sample; pass "full" to use the completed
# full-libgen harvest + video pool.
if len(sys.argv) > 1 and sys.argv[1] == "full":
    SOURCES = [("books3_authors.csv", "books3_books"),
               ("libgen_authors.csv", "libgen_books"),
               ("libgenfic_authors.csv", "libgenfic_books")]
else:
    SOURCES = [("books3_authors.csv", "books3_books"),
               ("libgen_sample.csv", "libgen_books")]

# --- noise filter: drop corporate/imprint/artifact "authors" ---
ORG_WORDS = re.compile(r"\b(publications?|publishing|publisher|press|editions?|books|"
    r"guides?|institute|institution|association|committee|commission|council|"
    r"department|ministry|bureau|society|organi[sz]ation|foundation|editors?|"
    r"editorial|staff|inc|llc|ltd|corp|corporation|company|group|media|studios?|"
    r"university|college|school|academy|agency|office|board|centre|center|network|"
    r"comics|entertainment|productions?|records|international|national|federation|"
    r"gmbh|verlag|oecd|unesco|who hq)\b", re.I)
ARTIFACT = re.compile(r"^(et al\.?|coll\.?|various(\s+authors)?|anonymous|unknown|"
    r"n/?a|no author|author unknown|aa\.?\s?vv\.?|aavv|s\.?n\.?|phd|m\.?d\.?|"
    r"editor|editors|compiler|translator|\W*|\d+.*)$", re.I)


NOISE_NAMES = {"lonely planet", "gooseberry patch", "dk", "marvel", "phd", "md",
    "na", "sn", "aavv", "etal", "usborne", "collectif", "collective", "vv aa",
    "readtrepreneur publishing", "the editors", "scholastic", "disney", "pixar",
    "hero collector", "mango media", "speedy publishing", "kidkraft"}


def is_individual(name):
    n = name.strip()
    flat = re.sub(r"[.\s]", "", n).lower()
    if len(n) < 3 or ARTIFACT.match(n) or flat in NOISE_NAMES:
        return False
    if n.strip().lower() in NOISE_NAMES:
        return False
    if ORG_WORDS.search(n):
        return False
    if "," not in n and " " not in n and not any(c.isupper() for c in n[1:]):
        return False  # single lowercase token
    return True


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split()).casefold()


# Public-domain authors (from Project Gutenberg, which hosts only PD works).
PD = set()
if os.path.exists("pd_authors.txt"):
    PD = {ln.strip() for ln in open("pd_authors.txt", encoding="utf-8") if ln.strip()}


def is_public_domain(name):
    return norm(name) in PD


def main():
    agg = {}   # norm -> {"name":display, cols..., "total":n}
    cols = []
    for path, col in SOURCES:
        if not os.path.exists(path):
            continue
        cols.append(col)
        for r in csv.DictReader(open(path, encoding="utf-8")):
            name = (r.get("name") or "").strip()
            if not name:
                continue
            try:
                n = int(r.get("fma_track_count") or 0)
            except ValueError:
                n = 0
            k = norm(name)
            e = agg.setdefault(k, {"name": name, "total": 0})
            e[col] = e.get(col, 0) + n
            e["total"] += n

    rows = sorted(agg.values(), key=lambda e: -e["total"])
    fields = (["rank", "author", "author_type", "public_domain", "total_books"] + cols
              + ["affected_by", "sued_over"])

    def write(path, viable_only):
        rank = 0
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for e in rows:
                indiv = is_individual(e["name"])
                pd = is_public_domain(e["name"])
                if viable_only and (not indiv or pd):
                    continue
                rank += 1
                row = {"rank": rank, "author": e["name"],
                       "author_type": "individual" if indiv else "org/artifact",
                       "public_domain": "yes" if pd else "",
                       "total_books": e["total"], "affected_by": "Meta (Llama)",
                       "sued_over": "Books3/LibGen shadow libraries; copyright + DMCA 1202"}
                for c in cols:
                    row[c] = e.get(c, 0)
                w.writerow(row)
        return rank

    total_all = write("meta_plaintiffs.csv", False)
    total_clean = write("meta_plaintiffs_clean.csv", True)
    viable = [e for e in rows if is_individual(e["name"]) and not is_public_domain(e["name"])]
    print(f"sources {cols}: {len(rows)} unique names")
    print(f"  meta_plaintiffs.csv (all, flagged): {total_all}")
    print(f"  meta_plaintiffs_clean.csv (viable = individual & not public-domain): {total_clean}")
    import collections
    b = collections.Counter("10+" if e["total"] >= 10 else "3-9" if e["total"] >= 3
                            else "2" if e["total"] == 2 else "1" for e in viable)
    print("viable by book count:", dict(b))
    print("top 20 viable:", ", ".join(f"{e['name']}({e['total']})" for e in viable[:20]))


if __name__ == "__main__":
    main()
