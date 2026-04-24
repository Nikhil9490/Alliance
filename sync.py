import json
from datetime import datetime, timezone
from pathlib import Path
from notion_db import NotionDB, NotionJobsDB

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

def load_last_schedules():
    return _load_state().get("last_schedules", {})

def save_last_schedules(last_schedules: dict):
    state = _load_state()
    state["last_schedules"] = last_schedules
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


STAGE_MAP = {
    "in progress":       "In Progress",
    "scheduled":         "scheduled",
    "needs scheduling":  "Lead Intake",
    "complete unrated":  "Completed",
    "complete rated":    "Completed",
    "pro canceled":      "Closed",
    "user canceled":     "Closed",
}

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
        "Job status":         {"rich_text": _text(STAGE_MAP.get(work_status, work_status))},
        "Checklist Complete": {"checkbox": checklist_complete},
    }
    if phone:
        props["Phone"] = {"phone_number": phone}
    stage = STAGE_MAP.get(work_status)
    if stage:
        props["Stages"] = {"select": {"name": stage}}
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
    last_schedules = load_last_schedules()
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
            if scheduled and scheduled != last_schedules.get(existing_hcp_id):
                try:
                    hcp.update_job_schedule(existing_hcp_id, scheduled)
                    last_schedules[existing_hcp_id] = scheduled
                except Exception as e:
                    if "400" in str(e):
                        pass  # completed/closed jobs can't be rescheduled
                    else:
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
                    notion.set_id(page_id, hcp_id)
                    tracked[page_id] = hcp_id
                created += 1
            except Exception as e:
                print(f"  Page {page_id}: {e}")
                errors += 1

    save_tracked_pages(tracked)
    save_last_notes(last_notes)
    save_last_schedules(last_schedules)
    print(f"  {created} created, {updated} updated, {deleted} deleted in HCP, {skipped} skipped, {errors} errors")


def sync_hcp_to_notion(hcp, notion: NotionJobsDB, max_pages=None):
    label = f"pages 1-{max_pages}" if max_pages else "all pages"
    print(f"HCP -> Notion ({label}) ...")
    page_num = 1
    total_pages = 1
    all_hcp_ids = set()
    created = updated = deleted = errors = 0
    full_sync = max_pages is None
    last_schedules = load_last_schedules()

    while page_num <= total_pages:
        if max_pages and page_num > max_pages:
            break
        try:
            data = hcp.list_jobs(page=page_num, per_page=50)
        except Exception as e:
            print(f"  Failed to fetch page {page_num} from HCP: {e}")
            break

        if isinstance(data, dict):
            total_pages = data.get("total_pages", 1)
            jobs = data.get("jobs") or data.get("data") or []
        else:
            jobs = data or []

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
                schedule = job.get("schedule") or {}
                sched_start = schedule.get("scheduled_start") if isinstance(schedule, dict) else None
                if sched_start:
                    last_schedules[str(job["id"])] = sched_start
            except Exception as e:
                print(f"  Job {job.get('id')}: {e}")
                errors += 1

        print(f"  Page {page_num}/{total_pages} done ({created} created, {updated} updated so far)")
        page_num += 1

    # Only check for deletions on a full sync (we have all HCP IDs)
    if full_sync and all_hcp_ids:
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

    save_last_schedules(last_schedules)
    print(f"  {created} created, {updated} updated, {deleted} archived, {errors} errors")


# ── leads mapping ──────────────────────────────────────────────────────────────

def hcp_lead_to_notion_props(lead):
    customer = lead.get("customer") or {}
    customer_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
    phone = customer.get("mobile_number") or ""
    email = customer.get("email") or ""

    addr = lead.get("address") or {}
    if isinstance(addr, dict):
        parts = [addr.get("street"), addr.get("city"), addr.get("state"), addr.get("zip")]
        address = ", ".join(p for p in parts if p)
    else:
        address = str(addr) if addr else ""

    employee = lead.get("assigned_employee") or {}
    employee_name = (
        f"{employee.get('first_name', '')} {employee.get('last_name', '')}".strip()
        if isinstance(employee, dict) else ""
    )

    tags = lead.get("tags") or []
    tag_names = [t.get("name", t) if isinstance(t, dict) else str(t) for t in tags]

    status = lead.get("status") or ""
    pipeline_status = lead.get("pipeline_status") or ""
    lead_source = lead.get("lead_source") or ""
    total_amount = lead.get("total_amount") or 0

    props = {
        "Lead #":        {"title": _text(f"Lead #{lead['number']}")},
        "Lead ID":       {"rich_text": _text(lead["id"])},
        "Customer Name": {"rich_text": _text(customer_name)},
        "Address":       {"rich_text": _text(address)},
        "Total Amount":  {"number": total_amount},
    }
    if phone:
        props["Phone"] = {"phone_number": phone}
    if email:
        props["Email"] = {"email": email}
    if status:
        props["Status"] = {"select": {"name": status}}
    if pipeline_status:
        props["Pipeline Status"] = {"select": {"name": pipeline_status}}
    if lead_source:
        props["Lead Source"] = {"select": {"name": lead_source}}
    if employee_name:
        props["Assigned Employee"] = {"rich_text": _text(employee_name)}
    if tag_names:
        props["Tags"] = {"multi_select": [{"name": t} for t in tag_names]}
    return props


# ── estimates mapping ──────────────────────────────────────────────────────────

def hcp_estimate_to_notion_props(estimate):
    customer = estimate.get("customer") or {}
    customer_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
    phone = customer.get("mobile_number") or ""
    email = customer.get("email") or ""

    addr = estimate.get("address") or {}
    if isinstance(addr, dict):
        parts = [addr.get("street"), addr.get("city"), addr.get("state"), addr.get("zip")]
        address = ", ".join(p for p in parts if p)
    else:
        address = str(addr) if addr else ""

    employees = estimate.get("assigned_employees") or []
    employee_names = ", ".join(
        f"{e.get('first_name', '')} {e.get('last_name', '')}".strip()
        for e in employees if isinstance(e, dict)
    )

    schedule = estimate.get("schedule") or {}
    scheduled_start = schedule.get("scheduled_start") if isinstance(schedule, dict) else None

    options = estimate.get("options") or []
    total_amount = sum(o.get("total_amount", 0) for o in options) if options else 0

    notes = ""
    if options:
        option_notes = options[0].get("notes") or []
        if option_notes:
            notes = option_notes[-1].get("content", "")

    work_status = estimate.get("work_status") or ""
    lead_source = estimate.get("lead_source") or ""
    job_type = ((estimate.get("estimate_fields") or {}).get("job_type") or {}).get("name") or ""

    props = {
        "Estimate #":    {"title": _text(estimate["estimate_number"])},
        "Estimate ID":   {"rich_text": _text(estimate["id"])},
        "Customer Name": {"rich_text": _text(customer_name)},
        "Address":       {"rich_text": _text(address)},
    }
    if phone:
        props["Phone"] = {"phone_number": phone}
    if email:
        props["Email"] = {"email": email}
    if work_status:
        props["Status"] = {"select": {"name": work_status}}
    if lead_source:
        props["Lead Source"] = {"select": {"name": lead_source}}
    if job_type:
        props["Job Type"] = {"select": {"name": job_type}}
    if scheduled_start:
        props["Scheduled"] = {"date": {"start": scheduled_start}}
    if employee_names:
        props["Assigned Employees"] = {"rich_text": _text(employee_names)}
    if notes:
        props["Notes"] = {"rich_text": _text(notes[:2000])}
    if total_amount:
        props["Total Amount"] = {"number": total_amount}
    return props


# ── leads sync ─────────────────────────────────────────────────────────────────

def sync_hcp_leads_to_notion(hcp, notion: NotionDB):
    print("HCP -> Notion (leads) ...")
    page_num = 1
    total_pages = 1
    created = updated = errors = 0

    while page_num <= total_pages:
        try:
            data = hcp.list_leads(page=page_num)
        except Exception as e:
            print(f"  Failed to fetch leads page {page_num}: {e}")
            break

        total_pages = data.get("total_pages", 1)
        leads = data.get("leads") or []
        if not leads:
            break

        for lead in leads:
            try:
                props = hcp_lead_to_notion_props(lead)
                action, _ = notion.upsert(lead["id"], props)
                if action == "created":
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                print(f"  Lead {lead.get('id')}: {e}")
                errors += 1

        page_num += 1

    print(f"  {created} created, {updated} updated, {errors} errors")


# ── estimates sync ─────────────────────────────────────────────────────────────

def sync_hcp_estimates_to_notion(hcp, notion: NotionDB):
    print("HCP -> Notion (estimates) ...")
    page_num = 1
    total_pages = 1
    created = updated = errors = 0

    while page_num <= total_pages:
        try:
            data = hcp.list_estimates(page=page_num)
        except Exception as e:
            print(f"  Failed to fetch estimates page {page_num}: {e}")
            break

        total_pages = data.get("total_pages", 1)
        estimates = data.get("estimates") or []
        if not estimates:
            break

        for estimate in estimates:
            try:
                props = hcp_estimate_to_notion_props(estimate)
                action, _ = notion.upsert(estimate["id"], props)
                if action == "created":
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                print(f"  Estimate {estimate.get('id')}: {e}")
                errors += 1

        page_num += 1

    print(f"  {created} created, {updated} updated, {errors} errors")
