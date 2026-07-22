#!/usr/bin/env python3
"""
Pull Jewish authors (secular writers + rabbis / Torah scholars / religious authors,
incl. the ArtScroll/Feldheim world) from Wikipedia category membership via the
MediaWiki API. Output: name (one per line).
Public-figure, category-based; approximate & incomplete — verify individually.
"""
import csv, json, sys, time, urllib.parse, urllib.request

UA = "AIWatchdogScreener/1.0 (research; contact: dovidysamson@gmail.com)"
API = "https://en.wikipedia.org/w/api.php"
OUT = sys.argv[1] if len(sys.argv) > 1 else "jewish_authors.csv"

SEEDS = [
    "Category:Jewish writers", "Category:American Jewish writers",
    "Category:Israeli Jewish writers", "Category:Jewish American writers",
    "Category:Writers about Judaism", "Category:Jewish religious writers",
    "Category:Orthodox rabbis", "Category:Haredi rabbis",
    "Category:American Orthodox rabbis", "Category:American Haredi rabbis",
    "Category:Talmudists", "Category:Posekim", "Category:Rosh yeshivas",
    "Category:Authors of books about Judaism", "Category:Hasidic rebbes",
    "Category:Modern Orthodox rabbis", "Category:20th-century American rabbis",
    "Category:21st-century American rabbis", "Category:Jewish theologians",
    "Category:Rabbis in New York City", "Category:American Jewish theologians",
    "Category:ArtScroll", "Category:Jewish children's writers",
]


def api(params):
    params.update({"action": "query", "format": "json"})
    url = API + "?" + urllib.parse.urlencode(params)
    for a in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            time.sleep(1.5 * (2 ** a))
    return {}


def members(cat, kinds):
    out, cont = [], {}
    while True:
        p = {"list": "categorymembers", "cmtitle": cat, "cmlimit": "500", "cmtype": kinds}
        p.update(cont)
        d = api(p)
        for m in d.get("query", {}).get("categorymembers", []):
            out.append((m["title"], m["ns"]))
        if "continue" in d:
            cont = d["continue"]; time.sleep(0.15)
        else:
            break
    return out


def main():
    people, subcats = set(), []
    for c in SEEDS:
        for title, ns in members(c, "page|subcat"):
            if ns == 14:
                subcats.append(title)
            elif ns == 0:
                people.add(title)
        time.sleep(0.1)
    for c in subcats:
        for title, ns in members(c, "page"):
            if ns == 0:
                people.add(title)
        time.sleep(0.1)
    bad = ("List of", "Category:", "Bibliography", "Outline of")
    names = sorted(n for n in people if not n.startswith(bad)
                   and "(disambiguation)" not in n)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["name"])
        for n in names:
            w.writerow([n])
    print(f"wrote {len(names)} Jewish authors from {len(subcats)} subcats -> {OUT}")
    print("sample:", ", ".join(names[:20]))


if __name__ == "__main__":
    main()
