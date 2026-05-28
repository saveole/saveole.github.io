#!/usr/bin/env python3
"""Sync running activities from Garmin CN to running-data/activities.json."""

import argparse
import io
import json
import os
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta

import garth
from fitparse import FitFile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_FILE = os.path.join(REPO_DIR, "running-data", "activities.json")
FIT_DIR = os.path.join(REPO_DIR, "running-data", "fit")


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


def download_fit(activity_id):
    """Download original FIT file for an activity using garth client.

    Garmin returns a ZIP archive containing the .fit file.
    Returns raw FIT bytes, or None if download fails.
    """
    try:
        fit_url = f"/download-service/files/activity/{activity_id}"
        raw = garth.client.download(fit_url)
        # Garmin wraps the FIT in a ZIP archive
        if raw[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                fit_names = [n for n in zf.namelist() if n.endswith(".fit")]
                if fit_names:
                    return zf.read(fit_names[0])
        return raw
    except Exception as e:
        print(f"  Failed to download FIT for {activity_id}: {e}")
        return None


def parse_fit_polyline(fit_bytes):
    """Parse FIT file bytes and extract GPS track as encoded polyline.

    FIT coordinates use semicircle units (180/2^31 degrees).
    Returns the Google Encoded Polyline string, or empty string if no GPS data.
    """
    try:
        fit_file = FitFile(io.BytesIO(fit_bytes))
    except Exception as e:
        print(f"    Failed to parse FIT file: {e}")
        return ""

    coords = []
    for record in fit_file.get_messages("record"):
        lat_data = record.get_value("position_lat")
        lon_data = record.get_value("position_long")

        if lat_data is not None and lon_data is not None:
            lat = lat_data * (180.0 / 2**31)
            lon = lon_data * (180.0 / 2**31)
            coords.append((lat, lon))

    if not coords:
        return ""

    # Thin: keep every 5th point when dataset is large (> 400 points).
    # Garmin records every second; 1 hour = 3600 points. Thinning cuts
    # volume by 80% while keeping the route visually smooth.
    if len(coords) > 400:
        coords = coords[::5]

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


def main():
    parser = argparse.ArgumentParser(description="Sync Garmin CN running data")
    parser.add_argument("--secret", help="Garmin secret string (or set GARMIN_SECRET env)")
    parser.add_argument(
        "--full-fit",
        action="store_true",
        help="Download FIT files for all activities (slow but gets full track data)",
    )
    parser.add_argument(
        "--fit-only",
        action="store_true",
        help="Only download FIT and update polylines, skip activity list fetch",
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

    # Load existing data for incremental sync
    existing = load_existing()

    if not args.fit_only:
        since_date = None
        if existing and not args.full_fit:
            yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
            since_date = yesterday
            print(f"Incremental sync from yesterday ({since_date})")

        activities = fetch_running_activities(since_date)
        print(f"Fetched {len(activities)} running activities")
    else:
        activities = fetch_running_activities()
        print(f"FIT-only mode: fetched {len(activities)} activity IDs from Garmin")

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

        if avg_hr and dist_km > 0:
            w = d["_hr_weight"] + dist_km
            d["avg_hr"] = (d["avg_hr"] * d["_hr_weight"] + avg_hr * dist_km) / w
            d["_hr_weight"] = w

        if cadence and dist_km > 0:
            w = d["_cadence_weight"] + dist_km
            d["cadence_spm"] = (d["cadence_spm"] * d["_cadence_weight"] + cadence * dist_km) / w
            d["_cadence_weight"] = w

        if activity_id:
            d["_activity_ids"].append(activity_id)

    # Download FIT and extract polylines for activities that don't have one yet
    needs_polyline = {}
    for date, d in day_map.items():
        existing_entry = existing.get(date)
        already_has = existing_entry and existing_entry.get("summary_polyline")
        if not already_has and d["_activity_ids"]:
            needs_polyline[date] = d["_activity_ids"]

    if needs_polyline:
        total_fit = sum(len(ids) for ids in needs_polyline.values())
        print(f"Downloading FIT for {total_fit} activities without polyline...")
        os.makedirs(FIT_DIR, exist_ok=True)

        for date, act_ids in needs_polyline.items():
            for act_id in act_ids:
                print(f"  Downloading FIT for activity {act_id} ({date})...")
                fit_bytes = download_fit(act_id)

                if fit_bytes:
                    fit_path = os.path.join(FIT_DIR, f"{act_id}.fit")
                    with open(fit_path, "wb") as f:
                        f.write(fit_bytes)

                    polyline = parse_fit_polyline(fit_bytes)
                    if polyline:
                        day_map[date]["summary_polyline"] = polyline
                        print(f"    Got polyline ({len(polyline)} chars)")
                    else:
                        print(f"    No GPS data (treadmill or indoor run)")
                else:
                    print(f"    Failed to download FIT")

    # Backfill polyline for existing entries missing it
    if args.full_fit or args.fit_only:
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
                continue
            if entry.get("summary_polyline"):
                continue
            act_ids = api_date_to_ids.get(date, [])
            if not act_ids:
                continue
            os.makedirs(FIT_DIR, exist_ok=True)
            for act_id in act_ids:
                print(f"  Backfill FIT for activity {act_id} ({date})...")
                fit_bytes = download_fit(act_id)
                if fit_bytes:
                    fit_path = os.path.join(FIT_DIR, f"{act_id}.fit")
                    with open(fit_path, "wb") as f:
                        f.write(fit_bytes)
                    polyline = parse_fit_polyline(fit_bytes)
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
