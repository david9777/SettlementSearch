# Deploying SettleSearch live (accessible from anywhere)

This guide answers two things:
1. **How the Refresh button actually works** (and where it can run).
2. **How to put the site online** so you can open it from any phone or computer.

---

## 1. How Refresh works

The project has **two separate parts**:

- **The viewer** (`index.html`, `styles.css`, `app.js`, `data.js`) — a plain website.
  It shows the data that's baked into `data.js`. This is what people see.
- **The engine** (`server.py`) — a small Python program that does the live pulling.

When you click **⟳ Refresh data**, here's the exact sequence:

1. Your browser sends a request to the local engine: `POST http://localhost:8765/api/refresh`.
2. `server.py` runs each **source connector** in turn (FTC, ClaimDepot, SEC, ~25 total).
   Each one reaches out over the internet, downloads that site's feed/sitemap/JSON,
   and extracts the case facts (name, amount if present, date, type, source link).
3. It **dedups** the new items against what you already have, **appends** the new ones,
   and writes them to `settlements.json` (the live store) and regenerates `data.js`.
4. It sends back a summary (e.g. "added 37 — Settlement 20, Lawsuit Filed 9, …").
5. The browser reloads the data and re-renders the table with the new records.

**No accounts, no API keys, no payment** — every source is public.

### Where can Refresh run?

| Situation | Does Refresh work? |
|-----------|--------------------|
| You run `python server.py` on **your** computer (Windows/Mac/Linux) | ✅ Yes |
| Any **other** computer that has Python + internet, running `python server.py` | ✅ Yes |
| The site is hosted as a **static website** (Option A below) | ❌ No button — it's view-only* |
| The **engine** is hosted on a Python host (Option B below) | ✅ Yes, for everyone |

\* On a static host the Refresh button shows a note telling you to run the engine
locally. The data is still there and fully searchable — you just update it from your
own machine and re-upload (takes 1 minute, see "Updating the live data").

**Bottom line:** the *viewer* runs anywhere (it's just a web page). The *live pull*
needs Python running somewhere. For most people the simplest setup is: host the viewer
publicly (Option A), and run Refresh locally whenever you want to update it.

---

## 2A. Put the viewer online — the easy way (recommended)

This hosts the website for free and makes it openable from any device. The data is
already inside `data.js`, so it works immediately. **You only need these 4 files:**

```
index.html
styles.css
app.js
data.js
```

### Method 1 — Netlify Drop (no account math, ~2 minutes)

1. Make a folder on your desktop, e.g. `settlesearch-site`, and copy those 4 files into it.
2. Go to **https://app.netlify.com/drop**.
3. **Drag the folder** onto the page.
4. Netlify gives you a live URL like `https://random-name-123.netlify.app` — open it on
   any phone or computer. Done.
5. (Optional) Free Netlify account → rename the site, or add a custom domain.

### Method 2 — GitHub Pages (free, permanent, easy to update)

1. Create a free GitHub account and a new **public** repository, e.g. `settlesearch`.
2. Upload the 4 files (`index.html`, `styles.css`, `app.js`, `data.js`) — the GitHub
   website has an "Add file → Upload files" button; no command line needed.
3. In the repo: **Settings → Pages → Build and deployment → Source: "Deploy from a
   branch" → Branch: `main` / `(root)` → Save.**
4. Wait ~1 minute. Your site is live at `https://<your-username>.github.io/settlesearch/`.

### Method 3 — Cloudflare Pages / Vercel

Same idea: create a project, point it at a folder/repo containing the 4 files, deploy.
No build command needed (it's a static site).

### Updating the live data

Whenever you want fresh settlements on the public site:

1. On your computer: `python server.py` → click **Refresh** (or run
   `python server.py --refresh-once`). This rewrites `data.js`.
2. Re-upload the new `data.js`:
   - **Netlify Drop:** drag the folder onto the drop page again.
   - **GitHub Pages:** upload the new `data.js` over the old one (it redeploys automatically).
3. The public site shows the new data within a minute (hard-refresh if your browser
   cached it: Ctrl/Cmd+Shift+R).

> Note: `data.js` is ~8 MB. Hosts compress it automatically, so visitors download
> roughly 1–2 MB once, then it's cached. Totally fine.

---

## 2C. Free, permanent, AND auto-updating (recommended for the firm) ⭐

This is the best **$0** setup: the site is a free static page on **GitHub Pages**, and
**GitHub Actions** (free) refreshes the data for you every 6 hours and commits it back to
the repo — so the data is **permanent** (stored in git history) and **always current**,
with nothing to pay for and no server to babysit. The only thing you give up vs. § 2B is
a click-to-refresh button for visitors; the 6-hourly auto-refresh replaces it (and you can
still trigger a refresh yourself from the Actions tab).

The workflow is already in the project at `.github/workflows/refresh.yml`.

### Step by step

1. **Put the project on GitHub.**
   - Free GitHub account → **New repository** (e.g. `lk-settlements`), **Public**
     (public repos get unlimited free Actions minutes).
   - Upload the **whole project folder** (every file, including the `.github` folder,
     `server.py`, `settlements.json`, and `data.js`).

2. **Let Actions write to the repo.**
   - Repo **Settings → Actions → General → Workflow permissions** → choose
     **"Read and write permissions"** → **Save**. (This lets the refresh bot commit the
     updated data. Without it the auto-commit step fails.)

3. **Turn on GitHub Pages.**
   - Repo **Settings → Pages → Build and deployment → Source: "Deploy from a branch" →
     Branch: `main` / `(root)` → Save.**
   - After ~1 minute your live site is at `https://<your-username>.github.io/lk-settlements/`.

4. **Kick off the first refresh (optional).**
   - Repo **Actions** tab → **"Refresh settlements"** workflow → **Run workflow**.
   - It pulls all ~25 sources, commits updated `settlements.json` + `data.js`, and Pages
     redeploys. From then on it runs **every 6 hours automatically**.

That's it — a free, firm-branded, self-updating settlement database at a public URL.

### Notes

- **Permanent:** every refresh is committed to git, so the data only grows and is fully
  versioned. Nothing resets, ever.
- **Cadence:** change `cron: "0 */6 * * *"` in `.github/workflows/refresh.yml` to refresh
  more or less often (it's standard cron, UTC).
- **The Refresh button** on the hosted page tells visitors the data updates automatically
  (it can't pull live without a server — that's § 2B). Your team never needs to click it.
- **Private repo?** Works too, but free Actions minutes are limited (~2,000/min per month —
  still plenty for a 6-hourly job). Public repos are unlimited.

---

## 2B. Host the *engine* live — Refresh button works for everyone ✅

This hosts `server.py` itself, so the live site serves the page **and** runs the pulls.
The code is already production-ready (binds the host's `$PORT`, has a refresh cooldown,
and ships `Procfile` / `requirements.txt` / `runtime.txt` / `render.yaml`).

**Recommended host: Render** (free tier, no credit card, outbound internet works).

### Step by step (Render)

1. **Put the project on GitHub.**
   - Create a free GitHub account → **New repository** (public or private), e.g. `settlesearch`.
   - Upload the **whole project folder** (every file, including `settlements.json`,
     `data.js`, and `render.yaml`). The web UI's "Add file → Upload files" works, or use
     git if you prefer. *(Do not skip `settlements.json` — it's the bundled baseline data.)*

2. **Create the service on Render.**
   - Sign up at **https://render.com** (free) and connect your GitHub.
   - Click **New → Blueprint**, pick your repo. Render reads `render.yaml` and fills in
     everything (build command, start command, Python version, cooldown). Click **Apply**.
   - *(Manual alternative: New → Web Service → choose the repo →
     Build command `pip install -r requirements.txt`, Start command `python server.py`,
     Instance type **Free** → Create.)*

3. **Wait ~2–3 minutes** for the first deploy. Render gives you a public URL like
   `https://settlesearch.onrender.com`. On first boot it seeds the database with the
   ~10,000-record baseline from `settlements.json`.

4. **Open it from any device.** The page loads, search works, and **⟳ Refresh data
   works for everyone** — it pulls all ~25 sources server-side and merges new records.
   The site also **auto-refreshes every 6 hours** on its own, so it stays current with no
   one clicking.

That's it. To update the code later, push to GitHub and Render auto-redeploys.

### Permanent storage (built in)

`render.yaml` provisions a **1 GB persistent disk** mounted at `/data`, and the app
stores its data in a **SQLite database** there (`DB_PATH=/data/settlements.db`). So
**every refresh is saved permanently** and survives restarts and redeploys — the data
only grows. This is why the blueprint uses the **Starter** instance (~$7/mo): persistent
disks aren't available on Render's free tier.

> Want a free trial first? In `render.yaml` change `plan: starter` → `plan: free` and
> delete the `disk:` block and the `DB_PATH` env var. It'll run free, but data resets to
> the baseline on each restart (good for kicking the tires, not for production).

**Always-on:** the Starter instance does **not** sleep, so there's no cold-start delay
for your team (free instances sleep after ~15 min idle).

### Bot protection (already built in)

Because the Refresh button is now public, the server enforces a **cooldown** (default
**120s** on Render, set by the `REFRESH_COOLDOWN` env var). Within that window a refresh
returns instantly with "just refreshed — try again in N s" instead of re-hitting 25 sites.
Set `REFRESH_COOLDOWN=0` to disable, or raise it to throttle harder.

### Other hosts

The same files work on **Railway** (`railway up`, has persistent volumes + $5 free
credit), **Fly.io** (`fly launch`, persistent volumes), or any **VPS** (`python server.py`
behind nginx). Avoid **PythonAnywhere free** — it blocks outbound to non-whitelisted sites,
which breaks the pulls.

---

## Quick reference

- **Run locally:** `python server.py` → http://localhost:8765 (data lives in `settlements.db`)
- **Refresh from command line:** `python server.py --refresh-once`
- **Export `data.js`** (for the static viewer-only deploy): `python server.py --export`
- **Reset the DB to the baseline:** delete `settlements.db` — it re-seeds from
  `settlements.json` on the next start. (To reset that baseline itself to the curated
  ~79: `Copy-Item settlements.seed.json settlements.json -Force`, then delete the DB.)
- **Files to deploy (full live site):** the whole folder (server + data + `render.yaml`).
- **Files to deploy (viewer only, no live refresh):** `index.html`, `styles.css`,
  `app.js`, `data.js`.

## Environment variables (live site)

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | 8765 | Set by the host; triggers binding to `0.0.0.0`. |
| `DB_PATH` | `./settlements.db` | Point at the persistent disk, e.g. `/data/settlements.db`. |
| `AUTO_REFRESH_HOURS` | `6` | Background auto-pull cadence. `0` disables. |
| `REFRESH_COOLDOWN` | `60` | Min seconds between real pulls (bot protection). |
| `SITE_NAME` | (none) | Optional firm label exposed at `/api/config`. |
