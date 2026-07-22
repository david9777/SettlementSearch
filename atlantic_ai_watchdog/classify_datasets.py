#!/usr/bin/env python3
"""
Fetch each dataset's "Learn more" article (URLs in datasets_config.py) and extract
the description + any "used by / used to train by <company>" or "downloaded" text,
so datasets can be classified USED_BY / DOWNLOADED_ONLY / ASSEMBLED_ONLY.

Usage: python classify_datasets.py <music|video>
Prints a suggested status per dataset; you still confirm/enter it in datasets_config.py.
"""
import re, sys, html, time, gzip
import urllib.request
from datasets_config import MODES

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
COMPANIES = ["Google", "Stability AI", "Stability", "Meta", "Nvidia", "NVIDIA",
             "ByteDance", "Snap", "Tencent", "Microsoft", "OpenAI", "Amazon",
             "Adobe", "Apple", "Baidu", "Alibaba", "Suno", "Udio", "Runway",
             "Anthropic", "Salesforce", "IBM", "Intel", "Hugging Face"]

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
          "Accept": "text/html", "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=40) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw.decode("utf-8", "ignore")

def article_text(h):
    h = re.sub(r"<script.*?</script>", " ", h, flags=re.S)
    h = re.sub(r"<style.*?</style>", " ", h, flags=re.S)
    h = re.sub(r"<[^>]+>", " ", h)
    t = re.sub(r"\s+", " ", html.unescape(h)).strip()
    i = t.find("A collection of")
    if i < 0:
        i = t.find("AI Watchdog:")
    j = t.find("Popular Links")
    k = t.find("Explore More Topics")
    end = min(x for x in [j, k, len(t)] if x > i) if i >= 0 else len(t)
    return t[i:end].strip() if i >= 0 else t[:1500]

def suggest(desc):
    low = desc.lower()
    used = ("used to train" in low or "was used" in low or
            "has been used by" in low or "used by" in low)
    dl = "downloaded" in low
    if used:
        return "USED_BY"
    if dl:
        return "DOWNLOADED_ONLY"
    return "ASSEMBLED_ONLY"

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "video"
    arts = MODES[mode]["article"]
    for slug in MODES[mode]["datasets"]:
        url = arts.get(slug)
        print("=" * 78)
        print(slug)
        if not url:
            print("  (no article URL in config)"); continue
        try:
            desc = article_text(fetch(url))
            comps = sorted({c for c in COMPANIES if re.search(r"\b"+re.escape(c)+r"\b", desc)},
                           key=lambda c: desc.find(c))
            print("  DESC:", desc[:500])
            print("  COMPANIES MENTIONED:", comps or "none")
            print("  SUGGESTED:", suggest(desc))
        except Exception as e:
            print("  ERR", e)
        time.sleep(0.6)

if __name__ == "__main__":
    main()
