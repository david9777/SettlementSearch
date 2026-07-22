# ECF → Teams Notifications — One-Time Setup

**Goal:** every time a new ECF document lands in any case's `Docket/ECF Documents` folder in SharePoint, a message is automatically posted to the **ECF Filings** channel in Teams with the case name, document name, and a link to the PDF.

**How it works:** each matter has its own SharePoint site (e.g. `/sites/5883`). A small script polls Microsoft Graph every few minutes for new files across all matter sites, filters for `ECF Documents` folders, and posts to Teams via a webhook. It runs on a schedule (GitHub Actions), keeps its own state so nothing is missed, and discovers new matter sites automatically.

---

## Part 1 — Microsoft 365 admin (one-time, ~10 minutes)

Whoever administers the firm's Microsoft 365 tenant needs to create an "app registration" so the script can read SharePoint. This grants **read-only** access — the app cannot modify, delete, or upload anything, and it cannot send mail or messages.

1. Go to **entra.microsoft.com** → **App registrations** → **New registration**
   - Name: `ECF-Teams-Notifier`
   - Supported account types: **Accounts in this organizational directory only** (single tenant)
   - Redirect URI: leave blank → **Register**
2. In the new app: **API permissions** → **Add a permission** → **Microsoft Graph** → **Application permissions** → search for and check **`Sites.Read.All`** → **Add permissions**
3. Click **Grant admin consent for Levi & Korsinsky** → Yes
4. **Certificates & secrets** → **New client secret** → description `ecf-notifier`, expiry **24 months** → **Add** → copy the **Value** immediately (it's only shown once)
5. Send back these three items (via a secure channel — not plain email if avoidable):
   - **Application (client) ID** (on the app's Overview page)
   - **Directory (tenant) ID** (same page)
   - The **client secret value** from step 4

> **If IT prefers tighter scoping:** `Sites.Selected` exists (per-site grants instead of tenant-wide read), but because every new matter creates a new site, each one would need an explicit grant — which defeats the automation. `Sites.Read.All` (read-only) is the pragmatic choice here.

## Part 2 — Teams webhook (any team member, ~2 minutes, no admin needed)

1. In Teams, create the channel that should receive pings (e.g. **ECF Filings**) if it doesn't exist yet.
2. Click the channel's **⋯** menu → **Workflows** → choose **"Post to a channel when a webhook request is received"** → accept the defaults → **Add workflow**
3. Copy the **HTTP URL** it gives you and send it to me. Treat that URL like a password — anyone who has it can post into the channel.

## Part 3 — What happens after that (my side)

1. Build the script: Graph delta polling across matter sites → filter `ECF Documents` → post adaptive card to the webhook.
2. Test against the HP case site (`/sites/5883`) only — drop a dummy PDF in, confirm the ping looks right.
3. Turn on tenant-wide discovery and schedule it (every ~10 minutes via GitHub Actions, in a private repo; credentials stored as encrypted Actions secrets, never in code).

**What a ping will look like:**

> **HP v. Acme Corp.**
> New ECF filing: **Dkt. 47 – Order Granting Motion to Compel.pdf**
> Open PDF · Docket / ECF Documents

## Notes

- **Missed runs are not missed pings.** The script tracks a change cursor per site; if a run is skipped, the next run picks up everything since the last successful one.
- **New cases need no registration.** New matter sites are discovered automatically on each run.
- **Rate limits.** With many matter sites, the script polls recently-active sites frequently and dormant ones lazily, staying well inside Microsoft's limits.
- **Read-only by design.** The Graph app can only read; posting to Teams happens through the channel webhook, which can only post to that one channel.
