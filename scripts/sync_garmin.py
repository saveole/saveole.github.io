#!/usr/bin/env python3
"""Sync running activities from Garmin CN to running-data/activities.json."""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import garth

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_FILE = os.path.join(REPO_DIR, "running-data", "activities.json")


def load_existing():
    if not os.path.exists(OUTPUT_FILE):
        return {}
    with open(OUTPUT_FILE, "r") as f:
        data = json.load(f)
    return {item["date"]: item["distance_km"] for item in data}


def save_output(day_map):
    result = [
        {"date": d, "distance_km": round(km, 1)}
        for d, km in sorted(day_map.items())
    ]
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(result)} days to {OUTPUT_FILE}")


def fetch_running_activities(since_date=None):
    garth.configure(domain="garmin.cn", ssl_verify=False)

    all_activities = []
    start = 0
    limit = 100

    while True:
        params = {
            "start": start,
            "limit": limit,
            "activityType": "running",
        }
        if since_date:
            params["startDate"] = since_date

        page = garth.connectapi(
            "/activitylist-service/activities/search/activities",
            params=params,
        )
        if not page:
            break
        all_activities.extend(page)
        if len(page) < limit:
            break
        start += limit

    return all_activities


def main():
    parser = argparse.ArgumentParser(description="Sync Garmin CN running data")
    parser.add_argument("--secret", help="Garmin secret string (or set GARMIN_SECRET env)")
    args = parser.parse_args()

    secret = args.secret or os.environ.get("GARMIN_SECRET")
    if not secret:
        print("Error: provide --secret or set GARMIN_SECRET env variable", file=sys.stderr)
        sys.exit(1)

    # Auth
    garth.configure(domain="garmin.cn", ssl_verify=False)
    garth.client.loads(secret)
    if garth.client.oauth2_token.expired:
        garth.client.refresh_oauth2()

    # Load existing data for incremental sync
    existing = load_existing()
    since_date = None
    if existing:
        since_date = min(existing.keys())
        print(f"Incremental sync from {since_date}")

    # Fetch
    activities = fetch_running_activities(since_date)
    print(f"Fetched {len(activities)} running activities")

    # Merge: aggregate by date
    day_map = dict(existing)
    for act in activities:
        start_local = act.get("startTimeLocal", "")
        if not start_local:
            continue
        date = start_local.split(" ")[0]
        distance_m = act.get("distance", 0) or 0
        distance_km = distance_m / 1000

        if date in day_map:
            # Sum if same date has multiple runs
            day_map[date] = day_map[date] + distance_km
        else:
            day_map[date] = distance_km

    save_output(day_map)


if __name__ == "__main__":
    main()
