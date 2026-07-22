#!/usr/bin/env python3
"""
Pull Jewish musicians from Wikipedia category membership via the MediaWiki API
(reliable; independent of the Wikidata Query Service). Walks a set of seed
categories plus one level of subcategories, collecting article (person) titles.

Output: name  (match by name in the AI Watchdog tool).
NOTE: Wikipedia-category based; public-figure data, approximate and incomplete.
For outreach segmentation only; verify individually.
"""
import csv, json, sys, time, urllib.parse, urllib.request

UA = "AIWatchdogScreener/1.0 (research; contact: dovidysamson@gmail.com)"
API = "https://en.wikipedia.org/w/api.php"
OUT = sys.argv[1] if len(sys.argv) > 1 else "jewish_musicians.csv"

SEEDS = [
    "Category:Jewish singers", "Category:Jewish American musicians",
    "Category:Jewish American songwriters", "Category:Jewish rappers",
    "Category:American Jewish musicians", "Category:Israeli Jewish musicians",
    "Category:Jewish American rock musicians", "Category:Jewish American record producers",
    "Category:Jewish women singers", "Category:Israeli musicians",
    "Category:Jewish classical musicians", "Category:Jewish jazz musicians",
]


def api(params):
    params.update({"action": "query", "format": "json"})
    url = API + "?" + urllib.parse.urlencode(params)
    for a in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            time.sleep(2 * (2 ** a))
    return {}


def members(cat, kinds):
    out, cont = [], {}
    while True:
        p = {"list": "categorymembers", "cmtitle": cat, "cmlimit": "500",
             "cmtype": kinds}
        p.update(cont)
        d = api(p)
        for m in d.get("query", {}).get("categorymembers", []):
            out.append((m["title"], m["ns"]))
        if "continue" in d:
            cont = d["continue"]; time.sleep(0.2)
        else:
            break
    return out


def main():
    people, cats = set(), list(SEEDS)
    # expand one level of subcategories
    subcats = []
    for c in SEEDS:
        for title, ns in members(c, "page|subcat"):
            if ns == 14:      # subcategory
                subcats.append(title)
            elif ns == 0:     # article (person)
                people.add(title)
        time.sleep(0.2)
    for c in subcats:
        for title, ns in members(c, "page"):
            if ns == 0:
                people.add(title)
        time.sleep(0.15)
    # drop obvious non-person pages
    bad = ("List of", "Category:", "Music of", "Jewish women in")
    names = sorted(n for n in people if not n.startswith(bad) and "(disambiguation)" not in n)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["name"])
        for n in names:
            w.writerow([n])
    print(f"wrote {len(names)} Jewish musicians from {len(subcats)} subcats -> {OUT}")
    print("sample:", ", ".join(names[:25]))


if __name__ == "__main__":
    main()
