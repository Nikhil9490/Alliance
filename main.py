import os
import time
import argparse
from dotenv import load_dotenv
from hcp import HCPClient
from notion_db import NotionJobsDB
from sync import sync_hcp_to_notion, sync_notion_to_hcp, save_sync_timestamp

load_dotenv()


def build_clients():
    hcp_key = os.getenv("HCP_API_KEY")
    notion_token = os.getenv("NOTION_TOKEN")
    db_id = os.getenv("NOTION_DATABASE_ID_JOBS")

    if not hcp_key:
        raise RuntimeError("HCP_API_KEY missing from .env")
    if not notion_token:
        raise RuntimeError("NOTION_TOKEN missing from .env")
    if not db_id:
        raise RuntimeError("NOTION_DATABASE_ID_JOBS missing from .env")

    return HCPClient(api_key=hcp_key), NotionJobsDB(token=notion_token, database_id=db_id)


def run_once(hcp, notion):
    sync_notion_to_hcp(notion, hcp)  # user changes → HCP first
    sync_hcp_to_notion(hcp, notion)  # then pull HCP state into Notion
    save_sync_timestamp()            # mark the boundary for next cycle


def run_loop(hcp, notion, interval_minutes):
    print(f"Polling every {interval_minutes} min — Ctrl+C to stop\n")
    while True:
        run_once(hcp, notion)
        print(f"\nNext sync in {interval_minutes} min ...\n")
        time.sleep(interval_minutes * 60)


def main():
    parser = argparse.ArgumentParser(description="HCP ↔ Notion sync")
    parser.add_argument("--once", action="store_true", help="Sync once and exit")
    parser.add_argument("--interval", type=int, default=5, help="Poll interval in minutes (default 5)")
    args = parser.parse_args()

    hcp, notion = build_clients()

    if args.once:
        run_once(hcp, notion)
    else:
        run_loop(hcp, notion, args.interval)


if __name__ == "__main__":
    main()
