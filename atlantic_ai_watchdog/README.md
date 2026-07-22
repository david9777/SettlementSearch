# Atlantic "AI Watchdog" screener — music & video

Screens a list of **music artists** or **YouTube creators** against The Atlantic's
**AI Watchdog** tool and flags anyone whose work appears in a dataset that
"**has been used by**" an AI company to train a model — i.e. targets to
investigate. A separate flag marks datasets that were only "**downloaded by**"
universities/institutes.

## How the tool works (verified by reconnaissance)

Public JSON API on the embedded app `https://ai-watchdog.embedded.theatlantic.com`.
Works **headlessly** — no browser, no login. `robots.txt` allows it with
`Crawl-delay: 1` (Anthropic's own crawler is blocked, which is why generic
web-fetch tools 404, but a normal client from your machine is fine).

- `GET  /api/autocomplete?q=<name>&dataset=<music|video>`
  → `{"suggestions":[{"name","id?","doc_count"}]}`.
  **music**: `id` is the artist's **MusicBrainz MBID**; `doc_count` is total tracks.
  **video**: no `id`.
- `POST /api/datasets/grouped`
  body `{"searchTerm","filters":[{"field":"dataset","values":[...]}],
  "resultsPerDataset":N[,"creatorId":<id>]}`
  → `{"datasetGroups":[{"name","totalCount"}],"totalResults":N}`.
  **music**: pass `creatorId` = MBID to isolate the exact artist.
  **video**: omit `creatorId`; the exact creator name isolates the channel.

### Datasets are a fixed set; "used by" is a per-dataset property

You classify each dataset **once** (in `datasets_config.py`) from its "Learn more"
article — `USED_BY` vs `DOWNLOADED_ONLY` — and it applies to every creator. You do
**not** click through per artist.

Classification is complete (2026-07-01) in `datasets_config.py`; `classify_datasets.py`
re-derives it from the article pages (theatlantic.com IS fetchable via local curl
with a browser UA — write output to a real path).

**Music (4) — only 1 is USED_BY:**
- `free-music-archive` → **USED_BY** (Google; Stability AI). CC tracks that forbid commercial use.
- `spotify-tracks-dataset` → DOWNLOADED_ONLY ("downloaded 70,000+ times")
- `laion-disco-12m`, `sleeping-disco-9m` → ASSEMBLED_ONLY (only "assembled by …")

**Video (11) — 7 USED_BY:**
- `runway-jupiter` → **USED_BY** (Runway) · `yttemporal-180m` → **USED_BY** (Stability AI, ByteDance)
- `internvid` → **USED_BY** (Stability AI, ByteDance) · `hdvila100m` → **USED_BY** (Meta, ByteDance, Snap, Tencent)
- `hdvg130m` → **USED_BY** (Nvidia) · `openvid1m` → **USED_BY** (Amazon, Microsoft, Nvidia, ByteDance, Kuaishou)
- `vidgen1m` → **USED_BY** (Amazon, Nvidia)
- `panda70m`, `koala36m`, `howto100m` → ASSEMBLED_ONLY · `youtube8m` → UNKNOWN (Atlantic's article link broken)

## Run

```bash
# music (artists)
python scrape.py --mode music --input artists.csv  --output music_results.csv \
                 --flagged-output music_flagged.csv

# video (YouTube creators)
python scrape.py --mode video --input channels.csv --output video_results.csv \
                 --flagged-output video_flagged.csv
```

- Input CSV header — music: `name[,mbid]` (give `mbid` for exact match; common
  names are ambiguous). video: `name` (exact YouTube channel name).
- Resumable: re-running with the same `--output` skips already-done names, so a
  million-row run can be stopped/restarted safely.
- Output columns: per-dataset counts, `present_datasets`, `used_by_datasets`,
  `used_by_companies`, and `flag`
  (`USED_BY` / `DOWNLOADED_ONLY` / `PRESENT_UNCLASSIFIED` / `NONE`).
- `--flagged-output` writes just the `USED_BY` rows = your target list.

Seed files included: `artists_seed.csv`, `channels_seed.csv` (both tested OK).

## Sourcing the name list (10k → 1M)

**Music:** the tool's IDs are MusicBrainz MBIDs, so MusicBrainz is the natural
source and IDs line up. Small runs: a `name,mbid` CSV (Kaggle Spotify sets, chart
exports). Large runs: the MusicBrainz **`mbdump`** `artist` table
(https://musicbrainz.org/doc/MusicBrainz_Database/Download) — every artist offline,
no API hammering. Prioritize by release count / popularity.

**Video:** need a YouTube channel-name list. Options: YouTube Data API channel
search, public "top YouTubers" / Social Blade exports, or Kaggle YouTube-channel
datasets. Exact channel names match best.

## Notes / caveats

- **Video flag is broad:** these datasets scraped YouTube widely, so essentially
  every large channel lands in `hdvila100m`/`yttemporal-180m`/`hdvg130m` and will
  flag `USED_BY`. Prioritize by the per-dataset **counts** (how much of their
  catalog was taken), not just the yes/no flag.
- Rate: ~1.2s/name → ~3k/hr (music makes 2 calls/name, video 1). 10k ≈ 1–2 hr,
  1M ≈ several days. Pre-filter to notable creators for large runs.
- This performs **targeted lookups**; it does not bulk-download the datasets
  themselves. Confirm the usage suits the site's terms for your purpose.
```
