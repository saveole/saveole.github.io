#!/usr/bin/env python3
"""Add a body measurement record to running-data/body.json."""

import json
import os
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_FILE = os.path.join(REPO_DIR, "running-data", "body.json")


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <weight_kg> <body_fat_pct> [date]")
        print(f"Example: {sys.argv[0]} 70.5 18.2")
        print(f"Example: {sys.argv[0]} 70.5 18.2 2026-05-20")
        sys.exit(1)

    weight = float(sys.argv[1])
    fat = float(sys.argv[2])
    d = sys.argv[3] if len(sys.argv) > 3 else date.today().isoformat()

    # Load existing
    records = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            records = json.load(f)

    # Check for duplicate date
    existing = {r["date"] for r in records}
    if d in existing:
        # Update existing record
        for r in records:
            if r["date"] == d:
                r["weight_kg"] = weight
                r["body_fat_pct"] = fat
                break
        print(f"Updated {d}: weight={weight}kg, body_fat={fat}%")
    else:
        records.append({"date": d, "weight_kg": weight, "body_fat_pct": fat})
        print(f"Added {d}: weight={weight}kg, body_fat={fat}%")

    # Save sorted by date
    records.sort(key=lambda r: r["date"])
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(records)} records to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
