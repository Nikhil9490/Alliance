# Alliance — HCP ↔ Notion Sync

Two-way sync between Housecall Pro (HCP) and a Notion jobs database. Runs as a polling script — no server required.

---

## File Structure

```
Alliance/
├── .env                # API keys (never commit)
├── hcp.py              # HCP API client
├── notion_db.py        # Notion DB wrapper
├── sync.py             # Sync logic (both directions) + state management
├── main.py             # Entry point (CLI)
├── requirements.txt
└── sync_state.json     # Auto-generated runtime state (never commit)
```

---

## Environment Variables (.env)

```
HCP_API_KEY=...                          # Housecall Pro API key
NOTION_TOKEN=...                         # Notion integration token
NOTION_DATABASE_ID_JOBS=...              # UUID of the Notion jobs database
JOBS_URL=...                             # Notion DB URL (not used in code, reference only)
```

---

## Notion Database Columns

The Notion DB must have these exact column names and types:

| Column | Type | Source |
|--------|------|--------|
| `Job #` | Title | `invoice_number` |
| `Job ID` | Text | `id` — used as dedup key |
| `Customer Name` | Text | `customer.first_name + last_name` |
| `Phone` | Phone | `customer.mobile_number` |
| `Address` | Text | `address.street, city, state, zip` |
| `Job status` | Text | `work_status` |
| `Stages` | Select | `work_status` |
| `Job Type` | Select | `job_fields.job_type.name` |
| `Job scheduled start date` | Date | `schedule.scheduled_start` |
| `Job created date` | Date | `created_at` |
| `Assigned Employees` | Text | `assigned_employees[].first_name last_name` |
| `Last Job Note` | Text | last item in `notes[].content` |
| `Checklist Complete` | Checkbox | `checklist_completed_at` |

These columns are Notion-only and are never touched by the sync:
- `Queue Owner` (Select)
- `AI Insight` (Text)
- `Priority` (Select)
- `Days Stuck` (Formula)
- `Last Updated` (Last edited time)

---

## HCP API

- Base URL: `https://api.housecallpro.com`
- Auth: `Authorization: Token {api_key}`
- Job ID format: `job_d7f80b1866c348e7882416f4992fa657` (prefixed string)

### Confirmed working endpoints

| Method | Path | Used for |
|--------|------|----------|
| GET | `/jobs?page=1&per_page=50` | List all jobs (paginated) |
| GET | `/jobs/{id}` | Get single job |
| POST | `/jobs` | Create job |
| PUT | `/jobs/{id}/schedule` | Update schedule — payload: `{"start_time": "ISO8601"}` |
| POST | `/jobs/{id}/notes` | Add note — payload: `{"content": "..."}` |
| DELETE | `/jobs/{id}` | Delete job (untested — may not be supported) |

### HCP API limitations (important)
There is NO generic `PUT /jobs/{id}` or `PATCH /jobs/{id}` endpoint. General job fields (customer name, address, status) **cannot be updated via the API**. Only schedule and notes can be written back to HCP.

---

## Sync Logic

### Sync order per cycle (important for loop prevention)
1. **Notion → HCP** runs first (pushes user edits before HCP overwrites Notion)
2. **HCP → Notion** runs second (pulls latest HCP state into Notion)
3. **Timestamp saved** — marks the boundary so next cycle only picks up new edits

### HCP → Notion
- Fetches all jobs from HCP (paginated)
- Creates or updates Notion rows matched by `Job ID`
- If a Notion row has a `Job ID` that no longer exists in HCP → archives the Notion page

### Notion → HCP

**New page (Job ID empty):**
- Creates a new job in HCP
- Writes the returned HCP `id` back to the `Job ID` field

**Existing page (has Job ID, edited since last sync):**
- Updates schedule via `PUT /jobs/{id}/schedule` (if `Job scheduled start date` is set)
- Adds a note via `POST /jobs/{id}/notes` (only if `Last Job Note` content changed — tracked in `sync_state.json` to avoid duplicate notes)

**Deleted page:**
- Tracked pages are stored in `sync_state.json`
- If a tracked page disappears from Notion, calls `DELETE /jobs/{id}` on HCP

### Loop prevention
- Notion → HCP runs before HCP → Notion in each cycle
- After HCP → Notion writes to Notion pages, the timestamp is saved
- Next cycle's Notion → HCP only picks up pages with `last_edited_time > last_sync`, so pages written by HCP → Notion are ignored

---

## State File (sync_state.json)

Auto-generated, gitignored. Contains:

```json
{
  "last_sync": "2026-04-22T20:55:49Z",
  "tracked_pages": {
    "<notion_page_id>": "<hcp_job_id>"
  },
  "last_notes": {
    "<hcp_job_id>": "last note content sent to HCP"
  }
}
```

---

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Sync once and exit
python main.py --once

# Poll continuously every 5 minutes
python main.py --interval 5

# Custom interval (e.g. every 10 minutes)
python main.py --interval 10
```

---

## Deployment

No server needed — just a machine that stays on.

| Option | Cost |
|--------|------|
| Local always-on machine | Free |
| Railway | ~$1–5/month |
| Render | ~$7/month |
| AWS Lambda + EventBridge (5-min cron) | Free tier |

Start command for any host: `python main.py --interval 5`

---

## Known Limitations

1. HCP API has no generic job update endpoint — only schedule and notes can be written back from Notion to HCP
2. Job deletion from HCP → Notion archives the Notion page (recoverable from Notion trash)
3. Job deletion from Notion → HCP calls DELETE on HCP (untested — verify HCP supports it before relying on this)
4. Notes in Notion (`Last Job Note`) only shows the most recent note from HCP; adding a note from Notion appends to HCP but doesn't overwrite existing notes
