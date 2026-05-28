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
    return {item["date"]: item for item in data}


def save_output(records_by_date):
    result = sorted(records_by_date.values(), key=lambda x: x["date"])
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
        yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
        since_date = yesterday
        print(f"Incremental sync from yesterday ({since_date})")

    # Fetch
    activities = fetch_running_activities(since_date)
    print(f"Fetched {len(activities)} running activities")

    # Aggregate by date
    day_map = {}
    for act in activities:
        start_local = act.get("startTimeLocal", "")
        if not start_local:
            continue
        parts = start_local.split(" ")
        date = parts[0]
        start_time = parts[1][:8] if len(parts) > 1 else ""
        act_type = act.get("activityType", {}).get("typeKey", "running")

        distance_m = act.get("distance") or 0
        duration_s = act.get("duration") or 0
        avg_hr = act.get("averageHR") or 0
        max_hr = act.get("maxHR") or 0
        cadence = act.get("averageRunningCadenceInStepsPerMinute") or 0
        vo2max = act.get("vO2MaxValue") or 0
        summary_polyline = act.get("summaryPolyline", "")

        if date not in day_map:
            day_map[date] = {
                "date": date,
                "start_time": start_time,
                "type": act_type,
                "distance_km": 0.0,
                "duration_s": 0,
                "avg_pace_s_per_km": 0,
                "avg_hr": 0.0,
                "max_hr": 0,
                "cadence_spm": 0.0,
                "vo2max": 0.0,
                "summary_polyline": "",
                "_hr_weight": 0.0,
                "_cadence_weight": 0.0,
            }

        d = day_map[date]
        dist_km = distance_m / 1000
        d["distance_km"] += dist_km
        d["duration_s"] += duration_s
        d["max_hr"] = max(d["max_hr"], max_hr)
        d["vo2max"] = max(d["vo2max"], vo2max)

        # Distance-weighted average for heart rate
        if avg_hr and dist_km > 0:
            w = d["_hr_weight"] + dist_km
            d["avg_hr"] = (d["avg_hr"] * d["_hr_weight"] + avg_hr * dist_km) / w
            d["_hr_weight"] = w

        # Distance-weighted average for cadence
        if cadence and dist_km > 0:
            w = d["_cadence_weight"] + dist_km
            d["cadence_spm"] = (d["cadence_spm"] * d["_cadence_weight"] + cadence * dist_km) / w
            d["_cadence_weight"] = w

        # Keep polyline from outdoor runs (prefer non-empty)
        if summary_polyline:
            d["summary_polyline"] = summary_polyline

    # Finalize: calculate pace from totals, round values, remove helper fields
    for d in day_map.values():
        d["distance_km"] = round(d["distance_km"], 1)
        if d["distance_km"] > 0 and d["duration_s"] > 0:
            d["avg_pace_s_per_km"] = round(d["duration_s"] / d["distance_km"])
        d["avg_hr"] = round(d["avg_hr"])
        d["cadence_spm"] = round(d["cadence_spm"], 1)
        d["vo2max"] = round(d["vo2max"], 1) if d["vo2max"] else 0
        del d["_hr_weight"]
        del d["_cadence_weight"]

    # Merge: fetched dates replace existing entries
    merged = dict(existing)
    merged.update(day_map)
    save_output(merged)


if __name__ == "__main__":
    main()
