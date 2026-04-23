# Alliance — HCP ↔ Notion Sync

Two-way sync between Housecall Pro (HCP) and Notion. Runs as a polling script — no server required.

---

## Current Status

### Done
- [x] Jobs: full HCP → Notion sync (320 jobs, all pages)
- [x] Jobs: Notion → HCP create (new Notion row → HCP job)
- [x] Jobs: Notion → HCP schedule update (`Job scheduled start date`)
- [x] Jobs: Notion → HCP note add (`Last Job Note`)
- [x] Jobs: deletion sync both directions
- [x] Stage mapping (raw HCP values → clean Notion select names)
- [x] Business hours enforcement (9 AM – 5 PM ET)
- [x] Two-interval polling: page-1 every 5 min, full scan every 60 min
- [x] HCP 429 rate limit handling (`RateLimit-Reset` header + retry)
- [x] Loop prevention via `sync_state.json` timestamp

### Next — Phase 2
- [ ] Leads DB: new Notion database synced from HCP `/leads`
- [ ] Estimates DB: new Notion database synced from HCP `/estimates`
- [ ] Link Estimates → Customers (relation)
- [ ] Link Jobs → Estimates (relation)

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
HCP_API_KEY=...                    # Housecall Pro API key (Token auth)
NOTION_TOKEN=...                   # Notion integration token
NOTION_DATABASE_ID_JOBS=...        # UUID of Notion jobs database
JOBS_URL=...                       # Notion DB URL (reference only)
```

Phase 2 will add:
```
NOTION_DATABASE_ID_LEADS=...
NOTION_DATABASE_ID_ESTIMATES=...
```

---

## HCP API

- Base URL: `https://api.housecallpro.com`
- Auth: `Authorization: Token {api_key}`
- Rate limit: undocumented number, returns `429` with `RateLimit-Reset` (epoch) header
- Job ID format: `job_d7f80b1866c348e7882416f4992fa657` (prefixed string)
- Page size: always returns 10 per page regardless of `per_page` param

### Confirmed endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/jobs?page=N` | List jobs (10/page, use `total_pages`) |
| GET | `/jobs/{id}` | Get single job |
| POST | `/jobs` | Create job |
| PUT | `/jobs/{id}/schedule` | Update schedule — `{"start_time": "ISO8601"}` |
| POST | `/jobs/{id}/notes` | Add note — `{"content": "..."}` |
| DELETE | `/jobs/{id}` | Delete job |
| GET | `/leads?page=N` | List leads — confirmed working |
| GET | `/estimates?page=N` | List estimates — confirmed working |

### HCP API limitations (important)
No generic `PUT /jobs/{id}` or `PATCH /jobs/{id}`. Cannot update customer name, address, status, job type, or assigned employees via API. Only schedule and notes can be written back to HCP from Notion.

---

## Notion — Jobs Database

### Column mapping

| Notion Column | Type | HCP Field |
|---------------|------|-----------|
| `Job #` | Title | `invoice_number` |
| `Job ID` | Text | `id` — dedup key |
| `Customer Name` | Text | `customer.first_name + last_name` |
| `Phone` | Phone | `customer.mobile_number` |
| `Address` | Text | `address.street, city, state, zip` |
| `Job status` | Text | `work_status` → mapped to clean name |
| `Stages` | Select | `work_status` → mapped to clean name |
| `Job Type` | Select | `job_fields.job_type.name` |
| `Job scheduled start date` | Date | `schedule.scheduled_start` |
| `Job created date` | Date | `created_at` |
| `Assigned Employees` | Text | `assigned_employees[].first_name last_name` |
| `Last Job Note` | Text | last item in `notes[].content` |
| `Checklist Complete` | Checkbox | `checklist_completed_at` |

### Stage mapping (HCP raw → Notion)

| HCP `work_status` | Notion `Stages` |
|-------------------|-----------------|
| `in progress` | `In Progress` |
| `scheduled` | `scheduled` |
| `needs scheduling` | `Lead Intake` |
| `complete unrated` | `Completed` |
| `complete rated` | `Completed` |
| `pro canceled` | `Closed` |
| `user canceled` | `Closed` |

### Notion-only columns (never touched by sync)
`Queue Owner`, `AI Insight`, `Priority`, `Days Stuck` (formula), `Last Updated` (system)

---

## Sync Logic

### Cycle order (loop prevention)
1. **Notion → HCP** — pushes user edits before HCP can overwrite them
2. **HCP → Notion** — pulls latest HCP state
3. **Save timestamp** — boundary for next cycle's change detection

### HCP → Notion
- Fetches all jobs paginated via `total_pages`
- Upserts each job to Notion matched by `Job ID`
- On full sync only: archives Notion pages whose `Job ID` no longer exists in HCP

### Notion → HCP
- New page (no Job ID) → `POST /jobs` → writes HCP ID back to Notion
- Existing page edited since last sync → `PUT /jobs/{id}/schedule` + `POST /jobs/{id}/notes` (if note changed)
- Deleted page (in `tracked_pages` but gone from Notion) → `DELETE /jobs/{id}`

### Loop prevention
Notion → HCP runs before HCP → Notion. After HCP → Notion writes pages, timestamp is saved. Next cycle's filter (`last_edited_time > last_sync`) skips those pages.

---

## State File (sync_state.json)

Auto-generated, gitignored:

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
# One-time full sync (ignores business hours)
python main.py --once

# Automated loop: page-1 every 5 min, full scan every 60 min, 9 AM–5 PM ET only
python main.py
```

### Polling schedule
- **Every 5 min**: page 1 only (~10 jobs, catches new jobs fast)
- **Every 60 min**: all pages (~320 jobs, catches updates + deletions)
- **Outside 9 AM–5 PM ET**: sleeps until next 9 AM

---

## Phase 2 Plan — Leads & Estimates

### HCP data available
- **Leads** (`/leads`): `id`, `number`, `customer`, `address`, `lead_source`, `status`, `pipeline_status`, `tags`, `total_amount`, `assigned_employee`, `conversions`, `job_fields`
- **Estimates** (`/estimates`): `id`, `estimate_number`, `work_status`, `customer`, `address`, `schedule`, `assigned_employees`, `options`, `estimate_fields`, `lead_source`

### Proposed Notion databases

**Leads DB** columns:
`Lead #` (title), `Lead ID` (text, dedup), `Customer Name`, `Phone`, `Address`, `Lead Source`, `Status`, `Pipeline Status`, `Tags`, `Total Amount`, `Assigned Employee`

**Estimates DB** columns:
`Estimate #` (title), `Estimate ID` (text, dedup), `Customer Name`, `Phone`, `Address`, `Status`, `Schedule`, `Assigned Employees`, `Lead Source`, `Options Count`, `Total Amount`

### Relations (to set up in Notion)
- Estimates → Customers (via Customer Name match)
- Jobs → Estimates (via `original_estimate_id` field on jobs)

### Notion env vars needed
Add to `.env`:
```
NOTION_DATABASE_ID_LEADS=...
NOTION_DATABASE_ID_ESTIMATES=...
```

### Code changes needed
1. Add `list_leads()` and `list_estimates()` to `hcp.py`
2. Create `NotionLeadsDB` and `NotionEstimatesDB` classes (or generalize `NotionJobsDB`)
3. Add `hcp_lead_to_notion_props()` and `hcp_estimate_to_notion_props()` to `sync.py`
4. Add `sync_hcp_leads_to_notion()` and `sync_hcp_estimates_to_notion()` to `sync.py`
5. Wire into `run_once()` in `main.py`

---

## Deployment

No server needed — just a machine that stays on.

| Option | Cost |
|--------|------|
| Local always-on machine | Free |
| Railway | ~$1–5/month |
| Render | ~$7/month |
| AWS Lambda + EventBridge | Free tier |

Start command: `python main.py`

---

## Known Limitations

1. HCP API has no generic job update endpoint — only schedule and notes can be written from Notion → HCP
2. HCP always returns 10 jobs/page regardless of `per_page` param
3. Notes in `Last Job Note` shows the most recent HCP note; adding from Notion appends a new note (doesn't overwrite)
4. Job deletion Notion → HCP calls `DELETE /jobs/{id}` — verify HCP supports this before relying on it
5. Notion API rate limit: 3 req/sec (Notion returns 429 with `Retry-After` header if exceeded)
