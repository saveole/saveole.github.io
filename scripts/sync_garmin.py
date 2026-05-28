#!/usr/bin/env python3
"""Sync running activities from Garmin CN to running-data/activities.json."""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta

import garth
import httpx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_FILE = os.path.join(REPO_DIR, "running-data", "activities.json")
GPX_DIR = os.path.join(REPO_DIR, "running-data", "gpx")

# Garmin CN API base URL
MODERN_URL = "https://connectapi.garmin.cn"

TIMEOUT = httpx.Timeout(120.0, connect=60.0)


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
    """Fetch activity list from Garmin CN."""
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


def download_gpx(activity_id, headers):
    """Download GPX file for a single activity from Garmin CN.

    Returns the raw GPX XML bytes, or None if download fails.
    """
    url = f"{MODERN_URL}/download-service/export/gpx/activity/{activity_id}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        print(f"  Failed to download GPX for {activity_id}: {e}")
        return None


def parse_gpx_polyline(gpx_bytes):
    """Parse GPX XML bytes and extract track points as encoded polyline.

    Returns the Google Encoded Polyline string, or empty string if no track points.
    """
    try:
        root = ET.fromstring(gpx_bytes)
    except ET.ParseError:
        return ""

    # GPX namespace
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}

    coords = []
    for trkpt in root.iter("{http://www.topografix.com/GPX/1/1}trkpt"):
        lat = trkpt.get("lat")
        lon = trkpt.get("lon")
        if lat and lon:
            coords.append((float(lat), float(lon)))

    if not coords:
        return ""

    return encode_polyline(coords)


def encode_polyline(coords):
    """Encode a list of (lat, lng) tuples into a Google Encoded Polyline string.

    Pure Python implementation — no external dependency needed.
    Reference: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
    """
    if not coords:
        return ""

    last_lat = 0
    last_lng = 0
    encoded = []

    for lat, lng in coords:
        # Round to 5 decimal places (~1m precision)
        lat_val = int(round(lat * 1e5))
        lng_val = int(round(lng * 1e5))

        delta_lat = lat_val - last_lat
        delta_lng = lng_val - last_lng

        encoded.append(_encode_signed(delta_lat))
        encoded.append(_encode_signed(delta_lng))

        last_lat = lat_val
        last_lng = lng_val

    return "".join(encoded)


def _encode_signed(value):
    """Encode a signed integer using the polyline encoding algorithm."""
    # ZigZag encoding: negative values become odd, positive become even
    if value < 0:
        value = ~(value << 1)
    else:
        value = value << 1

    chunks = []
    while value >= 0x20:
        chunks.append(chr((0x20 | (value & 0x1F)) + 63))
        value >>= 5
    chunks.append(chr(value + 63))
    return "".join(chunks)


def fetch_polyline_for_activity(activity_id, headers):
    """Download GPX for an activity and extract polyline.

    Returns encoded polyline string, or empty string if no GPS data.
    """
    gpx_bytes = download_gpx(activity_id, headers)
    if not gpx_bytes:
        return ""
    return parse_gpx_polyline(gpx_bytes)


def main():
    parser = argparse.ArgumentParser(description="Sync Garmin CN running data")
    parser.add_argument("--secret", help="Garmin secret string (or set GARMIN_SECRET env)")
    parser.add_argument(
        "--full-gpx",
        action="store_true",
        help="Download GPX files for all activities (slow but gets full polyline data)",
    )
    parser.add_argument(
        "--gpx-only",
        action="store_true",
        help="Only download GPX and update polylines, skip activity list fetch",
    )
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

    # Build auth headers for httpx requests
    auth_headers = {
        "Authorization": str(garth.client.oauth2_token),
        "User-Agent": "Mozilla/5.0",
        "nk": "NT",
    }

    # Load existing data for incremental sync
    existing = load_existing()

    if not args.gpx_only:
        # Fetch activities
        since_date = None
        if args.full_gpx:
            # Full GPX mode: fetch ALL activities to get their IDs for GPX download
            print("Full GPX mode: fetching all activities from Garmin")
        elif existing:
            yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
            since_date = yesterday
            print(f"Incremental sync from yesterday ({since_date})")

        activities = fetch_running_activities(since_date)
        print(f"Fetched {len(activities)} running activities")
    else:
        # In gpx-only mode, we need to reload activities to get their IDs
        # Load from existing data — we need activity IDs from Garmin
        activities = fetch_running_activities()
        print(f"GPX-only mode: fetched {len(activities)} activity IDs from Garmin")

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

        # Get activity ID for GPX download
        activity_id = act.get("activityId")

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
                "_activity_ids": [],
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

        # Collect activity IDs for GPX download
        if activity_id:
            d["_activity_ids"].append(activity_id)

    # Download GPX and extract polylines
    # Only for activities that don't already have polyline data
    needs_polyline = {}
    for date, d in day_map.items():
        existing_entry = existing.get(date)
        already_has = existing_entry and existing_entry.get("summary_polyline")
        if not already_has and d["_activity_ids"]:
            needs_polyline[date] = d["_activity_ids"]

    if needs_polyline:
        total_gpx = sum(len(ids) for ids in needs_polyline.values())
        print(f"Downloading GPX for {total_gpx} activities without polyline...")
        os.makedirs(GPX_DIR, exist_ok=True)

        for date, act_ids in needs_polyline.items():
            for act_id in act_ids:
                print(f"  Downloading GPX for activity {act_id} ({date})...")
                gpx_bytes = download_gpx(act_id, auth_headers)

                if gpx_bytes:
                    # Save GPX file for caching
                    gpx_path = os.path.join(GPX_DIR, f"{act_id}.gpx")
                    with open(gpx_path, "wb") as f:
                        f.write(gpx_bytes)

                    # Extract polyline from GPX
                    polyline = parse_gpx_polyline(gpx_bytes)
                    if polyline:
                        day_map[date]["summary_polyline"] = polyline
                        print(f"    Got polyline ({len(polyline)} chars)")
                    else:
                        print(f"    No GPS data (treadmill or indoor run)")
                else:
                    print(f"    Failed to download GPX")

    # Backfill polyline for existing entries missing it
    # Build a date->activityId map from the Garmin API response
    if args.full_gpx or args.gpx_only:
        api_date_to_ids = {}
        for act in activities:
            start_local = act.get("startTimeLocal", "")
            if not start_local:
                continue
            date = start_local.split(" ")[0]
            activity_id = act.get("activityId")
            if activity_id:
                api_date_to_ids.setdefault(date, []).append(activity_id)

        for date, entry in existing.items():
            if date in day_map:
                continue  # already handled above
            if entry.get("summary_polyline"):
                continue  # already has polyline
            act_ids = api_date_to_ids.get(date, [])
            if not act_ids:
                continue
            os.makedirs(GPX_DIR, exist_ok=True)
            for act_id in act_ids:
                print(f"  Backfill GPX for activity {act_id} ({date})...")
                gpx_bytes = download_gpx(act_id, auth_headers)
                if gpx_bytes:
                    gpx_path = os.path.join(GPX_DIR, f"{act_id}.gpx")
                    with open(gpx_path, "wb") as f:
                        f.write(gpx_bytes)
                    polyline = parse_gpx_polyline(gpx_bytes)
                    if polyline:
                        entry["summary_polyline"] = polyline
                        print(f"    Got polyline ({len(polyline)} chars)")
                    else:
                        print(f"    No GPS data (treadmill or indoor run)")

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
        del d["_activity_ids"]

    # Merge: fetched dates replace existing entries
    merged = dict(existing)
    merged.update(day_map)
    save_output(merged)


if __name__ == "__main__":
    main()
