import os
import time
import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from hcp import HCPClient
from notion_db import NotionDB, NotionJobsDB
from sync import (
    sync_hcp_to_notion, sync_notion_to_hcp,
    sync_hcp_leads_to_notion, sync_hcp_estimates_to_notion,
    save_sync_timestamp,
)

load_dotenv()

ET = ZoneInfo("America/New_York")
BUSINESS_START = 9   # 9 AM ET
BUSINESS_END   = 17  # 5 PM ET
QUICK_INTERVAL = 5   # minutes — jobs page 1 only
FULL_INTERVAL  = 60  # minutes — all pages


def is_business_hours():
    return BUSINESS_START <= datetime.now(ET).hour < BUSINESS_END


def seconds_until_open():
    now = datetime.now(ET)
    if now.hour < BUSINESS_START:
        opens = now.replace(hour=BUSINESS_START, minute=0, second=0, microsecond=0)
    else:
        opens = (now + timedelta(days=1)).replace(hour=BUSINESS_START, minute=0, second=0, microsecond=0)
    return (opens - now).total_seconds()


def build_clients():
    hcp_key      = os.getenv("HCP_API_KEY")
    notion_token = os.getenv("NOTION_TOKEN")
    jobs_db_id   = os.getenv("NOTION_DATABASE_ID_JOBS")
    leads_db_id  = os.getenv("NOTION_DATABASE_ID_LEADS")
    est_db_id    = os.getenv("NOTION_DATABASE_ID_ESTIMATES")

    if not hcp_key:      raise RuntimeError("HCP_API_KEY missing from .env")
    if not notion_token: raise RuntimeError("NOTION_TOKEN missing from .env")
    if not jobs_db_id:   raise RuntimeError("NOTION_DATABASE_ID_JOBS missing from .env")
    if not leads_db_id:  raise RuntimeError("NOTION_DATABASE_ID_LEADS missing from .env")
    if not est_db_id:    raise RuntimeError("NOTION_DATABASE_ID_ESTIMATES missing from .env")

    hcp       = HCPClient(api_key=hcp_key)
    jobs_db   = NotionJobsDB(token=notion_token, database_id=jobs_db_id)
    leads_db  = NotionDB(token=notion_token, database_id=leads_db_id,  id_prop="Lead ID")
    est_db    = NotionDB(token=notion_token, database_id=est_db_id,    id_prop="Estimate ID")

    return hcp, jobs_db, leads_db, est_db


def run_once(hcp, jobs_db, leads_db, est_db, full=True):
    sync_notion_to_hcp(jobs_db, hcp)
    sync_hcp_to_notion(hcp, jobs_db, max_pages=None if full else 1)
    if full:
        sync_hcp_leads_to_notion(hcp, leads_db)
        sync_hcp_estimates_to_notion(hcp, est_db)
    save_sync_timestamp()


def run_loop(hcp, jobs_db, leads_db, est_db):
    print(f"Sync loop: jobs page-1 every {QUICK_INTERVAL} min, full every {FULL_INTERVAL} min")
    print(f"Active hours: {BUSINESS_START} AM - {BUSINESS_END - 12} PM ET — Ctrl+C to stop\n")

    last_full = None

    while True:
        if not is_business_hours():
            wait = seconds_until_open()
            opens_at = (datetime.now(ET) + timedelta(seconds=wait)).strftime("%I:%M %p ET, %b %d")
            print(f"Outside business hours — sleeping until {opens_at} ...")
            time.sleep(wait)
            continue

        now = datetime.now(ET)
        now_str = now.strftime("%I:%M %p ET")

        if last_full is None or (now - last_full).total_seconds() >= FULL_INTERVAL * 60:
            print(f"[{now_str}] Full sync")
            run_once(hcp, jobs_db, leads_db, est_db, full=True)
            last_full = datetime.now(ET)
        else:
            mins_since = int((now - last_full).total_seconds() / 60)
            print(f"[{now_str}] Quick sync (full in {FULL_INTERVAL - mins_since} min)")
            run_once(hcp, jobs_db, leads_db, est_db, full=False)

        print(f"Next sync in {QUICK_INTERVAL} min\n")
        time.sleep(QUICK_INTERVAL * 60)


def main():
    parser = argparse.ArgumentParser(description="HCP <-> Notion sync")
    parser.add_argument("--once", action="store_true", help="Full sync once and exit")
    args = parser.parse_args()

    hcp, jobs_db, leads_db, est_db = build_clients()

    if args.once:
        run_once(hcp, jobs_db, leads_db, est_db, full=True)
    else:
        run_loop(hcp, jobs_db, leads_db, est_db)


if __name__ == "__main__":
    main()
