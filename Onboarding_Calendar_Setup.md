# Onboarding Tracker → Teams / Outlook Calendar Integration

How to connect `Onboarding_Tracker.xlsx` to your Teams/Outlook calendar so every
new hire's start date automatically becomes a calendar event.

## How it works

The workbook lives in your Teams channel's **Files** tab (which is SharePoint under
the hood). A scheduled **Power Automate** flow reads the `OnboardingTable` every
morning, and for each row that has a name + start date but no "Yes" in **Added to
Calendar**, it:

1. Creates an all-day event on the onboarding calendar ("First Day: Dana Whitfield — Paralegal"),
2. (optional) Posts an announcement in the Teams channel,
3. Writes **Yes** into *Added to Calendar* so the event is never created twice.

Edits are picked up on the next run. Nobody ever "imports" anything by hand.

## Prerequisites

- The workbook is already flow-ready: the data area is an Excel **table** named
  `OnboardingTable` (Power Automate can only read tables, not loose cells). Don't
  rename it or convert it to a range.
- A Microsoft 365 work account. Everything below uses **standard** connectors
  (Excel Online (Business), Office 365 Outlook, Microsoft Teams) — included in
  regular M365 business/enterprise licenses, no premium Power Automate license.
- Delete the sample row (Dana Whitfield, row 2) before going live.
- Decide who owns the flow (usually the HR person who owns the tracker). The flow
  runs under their account; add a second person as **co-owner** so it survives
  vacations/departures.

## Part 1 — Put the workbook where Teams can see it

1. In Teams, open the channel the HR/onboarding team uses (e.g. **HR › Onboarding**).
2. Go to the **Files** tab → **Upload** → pick `Onboarding_Tracker.xlsx`.
3. Done — the file is now in the team's SharePoint site and co-editable by the team.
   **Keep it here.** Moving or renaming it later breaks the flow connection.

## Part 2 — Pick the target calendar

- **Option A (recommended): a shared "New Hire Onboarding" calendar.**
  In Outlook: right-click **Calendars → Add calendar → Create blank calendar**, name it
  "New Hire Onboarding", then share it with the team (or with Amanda/Mark/Ed/etc.)
  with *can view* rights. The flow owner needs *can edit* rights (automatic if they
  created it). Native Power Automate actions write to it directly.
- **Option B: the Teams channel calendar itself.** That calendar is the M365 *group*
  calendar, which the standard Outlook action can't write to — it needs a small
  Graph call. Works fine, slightly more fiddly. See "Option B" at the bottom.

Either way, you can ALSO invite the new hire and their manager directly (Part 5) —
invitees see the event on their own calendars regardless of which option you pick.

## Part 3 — Build the flow (one time, ~15 minutes)

1. Go to **make.powerautomate.com** → sign in with the work account.
2. **Create → Scheduled cloud flow.** Name: `New Hire → Onboarding Calendar`.
   Repeat every **1 Day**, starting **7:00 AM**. Create.
3. **+ New step → Excel Online (Business) → "List rows present in a table"**
   - **Location:** the team's SharePoint site (pick "Group – <Team name>" or browse SharePoint sites)
   - **Document Library:** Documents
   - **File:** browse to `Onboarding_Tracker.xlsx`
   - **Table:** `OnboardingTable`
   - **Show advanced options → DateTime Format: `ISO 8601`** ← critical. Without
     this, Start Date arrives as an Excel serial number like `46247` instead of a date.
4. **+ New step → Condition.** Add three rows (AND):
   - Expression `empty(item()?['Candidate Name'])` **is equal to** `false`
   - Expression `empty(item()?['Start Date'])` **is equal to** `false`
   - Dynamic content `Added to Calendar` **is not equal to** `Yes`

   (Picking dynamic content from the Excel step auto-wraps the condition in an
   **Apply to each** loop — that's expected.)
5. In the **If yes** branch → **Office 365 Outlook → "Create event (V4)"**
   - **Calendar id:** `New Hire Onboarding` (the shared calendar from Part 2)
   - **Subject:** `First Day: ` + *Candidate Name* + ` — ` + *Position* (dynamic content)
   - **Start time** (expression): `formatDateTime(item()?['Start Date'], 'yyyy-MM-dd')`
   - **End time** (expression): `formatDateTime(addDays(item()?['Start Date'], 1), 'yyyy-MM-dd')`
     (all-day events must end the following midnight)
   - **Time zone:** `(UTC-05:00) Eastern Time (US & Canada)`
   - **Is all day event?:** `Yes`
   - **Reminder:** `2880` (minutes = 2 days before — the IT laptop-prep nudge)
   - **Body:** e.g.
     `Position: <Position> | Location: <Work Location> | Laptop: <Laptop Needed> | Manager: <Reporting To> | Email: <Email>`
   - **Required attendees** (optional): the *Email* dynamic content invites the new
     hire; see Part 5 for auto-inviting the manager.
6. Still in **If yes** → **Excel Online (Business) → "Update a row"**
   - Same Location / Library / File / Table as step 3
   - **Key Column:** `Candidate Name` — **Key Value:** dynamic *Candidate Name*
   - **Added to Calendar:** `Yes`
   - (If two hires could ever share a name, use `Email` as the key column instead.)
7. **Save**, then **Test → Manually**. First run will ask you to sign in to the
   Excel/Outlook/Teams connectors — one click each. Check the calendar: with the
   sample row deleted and one real row entered, you should see one event and the
   row's *Added to Calendar* flip to **Yes** (green).

## Part 3b — Prep reminder a week before (on the flow owner's calendar)

A second **Create event (V4)** in the same **If yes / True** branch, right after the
first one:

- **Calendar id:** `Calendar` (the flow owner's own default calendar)
- **Subject:** `Onboarding prep: ` + *Candidate Name* + ` - starts ` +
  expression `formatDateTime(item()?['Start Date'], 'MM/dd')`
- **Start time:** `formatDateTime(addDays(item()?['Start Date'], -7), 'yyyy-MM-dd')`
- **End time:** `formatDateTime(addDays(item()?['Start Date'], -6), 'yyyy-MM-dd')`
- **Is all day event?:** `Yes` · **Time zone:** Eastern
- **Body:** `Laptop: <Laptop Needed> | Location: <Work Location> | Manager: <Reporting To> | Email: <Email>`

Note: a hire entered with less than a week's notice gets a prep event in the past
(harmless, but easy to miss).

To push either event onto people's own calendars, add their addresses (or a
distribution list) to **Required attendees** on that Create event action, with
**Response requested = No** and **Show as = Free**. Invitees see it on their
regular calendar (tentative until accepted). Caution: every run that creates an
event sends real invites — don't test with real attendees and fake hires.

## Part 4 (optional) — Announce in the Teams channel

In the **If yes** branch, after the event: **Microsoft Teams → "Post message in a
chat or channel"** → Post as **Flow bot**, pick the Team + channel:

> 🎉 **<Candidate Name>** joins as **<Position>** on **<Start Date>** (<Work Location>).
> Manager: <Reporting To> · Laptop needed: <Laptop Needed>

## Part 5 (optional) — Auto-invite the manager

The *Reporting To* column holds first names, so the flow needs a name → email map:

1. Fill in the yellow **Manager Email** column on the workbook's **Lists** tab
   (documentation for humans), and
2. In the flow, before "Create event (V4)": **Control → Switch** on *Reporting To*.
   Case `Amanda` → **Set variable** `managerEmail` = `amanda@...`; case `Mark` → …
   (7 cases). Initialize the string variable at the top of the flow.
3. Add the `managerEmail` variable to **Required attendees** alongside the new
   hire's email.

## Option B — Write to the Teams channel calendar itself

The channel calendar is the team's Microsoft 365 **group** calendar. Replace
"Create event (V4)" with:

1. Get the team's **Group ID**: in Teams, click **⋯** next to the team name →
   **Get link to team** → copy the `groupId=...` value out of the URL.
2. Action: **Office 365 Groups → "Send an HTTP request"** (still a standard connector)
   - **URI:** `https://graph.microsoft.com/v1.0/groups/<GROUP-ID>/events`
   - **Method:** `POST`
   - **Body:**
     ```json
     {
       "subject": "First Day: @{item()?['Candidate Name']} — @{item()?['Position']}",
       "isAllDay": true,
       "start": { "dateTime": "@{formatDateTime(item()?['Start Date'],'yyyy-MM-dd')}T00:00:00", "timeZone": "Eastern Standard Time" },
       "end":   { "dateTime": "@{formatDateTime(addDays(item()?['Start Date'],1),'yyyy-MM-dd')}T00:00:00", "timeZone": "Eastern Standard Time" },
       "body":  { "contentType": "text", "content": "Location: @{item()?['Work Location']} | Laptop: @{item()?['Laptop Needed']} | Manager: @{item()?['Reporting To']}" }
     }
     ```
3. The flow owner must be a **member** of the team. Events appear on the channel's
   calendar tab and in every member's "group calendars" section in Outlook.

## Fallback — one-time manual import (no automation)

For a quick one-off without Power Automate: build a CSV with columns
`Subject, Start Date, All Day Event` (Subject = name + position), then in Outlook
desktop: **File → Open & Export → Import/Export → Import from another program or
file → Comma Separated Values** → choose the target calendar → map the fields.
Snapshot only — later edits in Excel don't sync.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Event date shows a number like `46247` | *DateTime Format* on "List rows" isn't `ISO 8601` (Part 3, step 3). |
| `formatDateTime` error on a run | A row has a name but a blank/text Start Date — the date must be a real date (the cell validation blocks text, but a pasted value can sneak through). |
| Rows never get processed | *Added to Calendar* already says Yes, or name/start date is blank, or the row was typed **below** the table without the table expanding (type in the striped area). |
| Duplicate events | Someone cleared the *Added to Calendar* column — the flow treats blank as "not booked yet". |
| "Update a row" fails | Duplicate or changed Candidate Name between the read and the write; switch the key column to `Email`. |
| Flow stopped after someone left the firm | The flow ran under their account. Open the flow → add a co-owner now, and reassign connections if needed. |
| Everything broke at once | The file was moved, renamed, or the table was converted to a range. Restore the name/location, or re-point the two Excel actions. |
