import json
from datetime import datetime, timezone
from pathlib import Path
from notion_db import NotionJobsDB

SYNC_STATE_FILE = Path("sync_state.json")


# ── state helpers ─────────────────────────────────────────────────────────────

def _load_state():
    try:
        return json.loads(SYNC_STATE_FILE.read_text())
    except Exception:
        return {}

def _save_state(state: dict):
    SYNC_STATE_FILE.write_text(json.dumps(state, indent=2))

def load_last_sync():
    return _load_state().get("last_sync")

def save_sync_timestamp():
    state = _load_state()
    state["last_sync"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

def load_tracked_pages():
    return _load_state().get("tracked_pages", {})

def save_tracked_pages(tracked: dict):
    state = _load_state()
    state["tracked_pages"] = tracked
    _save_state(state)

def load_last_notes():
    return _load_state().get("last_notes", {})

def save_last_notes(last_notes: dict):
    state = _load_state()
    state["last_notes"] = last_notes
    _save_state(state)


# ── property helpers ───────────────────────────────────────────────────────────

def _text(val):
    return [{"text": {"content": str(val) if val is not None else ""}}]

def _get_rich_text(props, name):
    items = (props.get(name) or {}).get("rich_text") or []
    return "".join(i.get("plain_text", "") for i in items).strip()

def _get_title(props, name):
    items = (props.get(name) or {}).get("title") or []
    return "".join(i.get("plain_text", "") for i in items).strip()

def _get_phone(props, name):
    return (props.get(name) or {}).get("phone_number") or ""

def _get_select(props, name):
    sel = (props.get(name) or {}).get("select")
    return sel.get("name", "") if isinstance(sel, dict) else ""

def _get_date(props, name):
    d = (props.get(name) or {}).get("date")
    return d.get("start") if isinstance(d, dict) else None


# ── HCP → Notion mapping ───────────────────────────────────────────────────────

def hcp_job_to_notion_props(job):
    customer = job.get("customer") or {}
    customer_name = (
        f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
        or customer.get("name", "")
    )
    phone = customer.get("mobile_number") or customer.get("home_number") or ""

    addr = job.get("address") or {}
    if isinstance(addr, dict):
        parts = [addr.get("street"), addr.get("city"), addr.get("state"), addr.get("zip")]
        address = ", ".join(p for p in parts if p)
    else:
        address = str(addr) if addr else ""

    title = job.get("invoice_number") or f"Job {job['id']}"
    work_status = job.get("work_status") or job.get("status") or ""

    schedule = job.get("schedule") or {}
    scheduled_start = schedule.get("scheduled_start") if isinstance(schedule, dict) else None
    created_at = job.get("created_at") or ""

    employees = job.get("assigned_employees") or []
    employee_names = ", ".join(
        f"{e.get('first_name', '')} {e.get('last_name', '')}".strip()
        for e in employees if isinstance(e, dict)
    )

    notes = job.get("notes") or []
    last_note = notes[-1].get("content", "") if notes else ""

    job_type = ((job.get("job_fields") or {}).get("job_type") or {}).get("name") or ""
    checklist_complete = bool(job.get("checklist_completed_at") or job.get("checklist_complete"))

    props = {
        "Job #":              {"title": _text(title)},
        "Job ID":             {"rich_text": _text(job["id"])},
        "Customer Name":      {"rich_text": _text(customer_name)},
        "Address":            {"rich_text": _text(address)},
        "Job status":         {"rich_text": _text(work_status)},
        "Checklist Complete": {"checkbox": checklist_complete},
    }
    if phone:
        props["Phone"] = {"phone_number": phone}
    if work_status:
        props["Stages"] = {"select": {"name": work_status}}
    if job_type:
        props["Job Type"] = {"select": {"name": job_type}}
    if scheduled_start:
        props["Job scheduled start date"] = {"date": {"start": scheduled_start}}
    if created_at:
        props["Job created date"] = {"date": {"start": created_at}}
    if employee_names:
        props["Assigned Employees"] = {"rich_text": _text(employee_names)}
    if last_note:
        props["Last Job Note"] = {"rich_text": _text(last_note[:2000])}

    return props


# ── Notion → HCP mapping ───────────────────────────────────────────────────────

def notion_page_to_hcp_create_payload(page):
    """Returns None if there is not enough info to create a job in HCP."""
    props = page.get("properties", {})
    customer_name = _get_rich_text(props, "Customer Name")
    if not customer_name:
        return None

    parts = customer_name.split(" ", 1)
    payload = {
        "customer": {
            "first_name": parts[0],
            "last_name": parts[1] if len(parts) > 1 else "",
        }
    }
    phone = _get_phone(props, "Phone")
    if phone:
        payload["customer"]["mobile_number"] = phone

    address = _get_rich_text(props, "Address")
    if address:
        payload["address"] = {"street": address}

    scheduled = _get_date(props, "Job scheduled start date")
    if scheduled:
        payload["schedule"] = {"start_time": scheduled}

    job_type = _get_select(props, "Job Type")
    if job_type:
        payload["job_type"] = job_type

    return payload


# ── sync functions ─────────────────────────────────────────────────────────────

def sync_notion_to_hcp(notion: NotionJobsDB, hcp):
    """
    Run BEFORE sync_hcp_to_notion so pages written by that step
    don't get mistaken for user edits in the same cycle.
    """
    last_sync = load_last_sync()
    tracked = load_tracked_pages()
    last_notes = load_last_notes()
    print(f"Notion -> HCP (changes since: {last_sync or 'never'}) ...")
    created = updated = deleted = skipped = errors = 0

    # ── detect deleted Notion pages → delete from HCP ──
    if tracked:
        current_ids = {p["id"] for p in notion.get_all_pages_with_job_id()}
        for page_id, hcp_id in list(tracked.items()):
            if page_id not in current_ids:
                try:
                    hcp.delete_job(hcp_id)
                    del tracked[page_id]
                    deleted += 1
                    print(f"  Deleted HCP job {hcp_id} (Notion page removed)")
                except Exception as e:
                    print(f"  Could not delete HCP job {hcp_id}: {e}")
                    errors += 1

    # ── sync new / updated pages ──
    if last_sync:
        notion_filter = {
            "or": [
                {"property": "Job ID", "rich_text": {"is_empty": True}},
                {
                    "and": [
                        {"property": "Job ID", "rich_text": {"is_not_empty": True}},
                        {"timestamp": "last_edited_time", "last_edited_time": {"after": last_sync}},
                    ]
                },
            ]
        }
    else:
        notion_filter = {"property": "Job ID", "rich_text": {"is_empty": True}}

    for page in notion.query(filter=notion_filter):
        page_id = page["id"]
        props = page.get("properties", {})
        existing_hcp_id = _get_rich_text(props, "Job ID")

        if existing_hcp_id:
            # Update: schedule and notes only (HCP API limitation)
            job_errors = 0

            scheduled = _get_date(props, "Job scheduled start date")
            if scheduled:
                try:
                    hcp.update_job_schedule(existing_hcp_id, scheduled)
                except Exception as e:
                    print(f"  Schedule update failed for {existing_hcp_id}: {e}")
                    job_errors += 1

            note = _get_rich_text(props, "Last Job Note")
            if note and note != last_notes.get(existing_hcp_id):
                try:
                    hcp.add_job_note(existing_hcp_id, note)
                    last_notes[existing_hcp_id] = note
                except Exception as e:
                    print(f"  Note failed for {existing_hcp_id}: {e}")
                    job_errors += 1

            if job_errors:
                errors += 1
            else:
                updated += 1
            tracked[page_id] = existing_hcp_id

        else:
            # Create new job in HCP
            payload = notion_page_to_hcp_create_payload(page)
            if not payload:
                skipped += 1
                continue
            try:
                result = hcp.create_job(payload)
                hcp_id = result.get("id")
                if hcp_id:
                    notion.set_hcp_id(page_id, hcp_id)
                    tracked[page_id] = hcp_id
                created += 1
            except Exception as e:
                print(f"  Page {page_id}: {e}")
                errors += 1

    save_tracked_pages(tracked)
    save_last_notes(last_notes)
    print(f"  {created} created, {updated} updated, {deleted} deleted in HCP, {skipped} skipped, {errors} errors")


def sync_hcp_to_notion(hcp, notion: NotionJobsDB):
    print("HCP -> Notion ...")
    page_num = 1
    all_hcp_ids = set()
    created = updated = deleted = errors = 0

    while True:
        try:
            data = hcp.list_jobs(page=page_num, per_page=50)
        except Exception as e:
            print(f"  Failed to fetch page {page_num} from HCP: {e}")
            break

        jobs = data if isinstance(data, list) else (data.get("jobs") or data.get("data") or [])
        if not jobs:
            break

        for job in jobs:
            all_hcp_ids.add(str(job["id"]))
            try:
                props = hcp_job_to_notion_props(job)
                action, _ = notion.upsert(job["id"], props)
                if action == "created":
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                print(f"  Job {job.get('id')}: {e}")
                errors += 1

        if isinstance(data, list) or len(jobs) < 50:
            break
        page_num += 1

    # Archive Notion pages whose HCP job was deleted
    if all_hcp_ids:
        for page in notion.get_all_pages_with_job_id():
            hcp_id = _get_rich_text(page.get("properties", {}), "Job ID")
            if hcp_id and hcp_id not in all_hcp_ids:
                try:
                    notion.archive_page(page["id"])
                    deleted += 1
                    print(f"  Archived Notion page for deleted HCP job {hcp_id}")
                except Exception as e:
                    print(f"  Could not archive page for job {hcp_id}: {e}")
                    errors += 1

    print(f"  {created} created, {updated} updated, {deleted} archived, {errors} errors")
