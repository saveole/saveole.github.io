#!/usr/bin/env python3
"""Aggregate daily token usage .data (TSV) files and print a summary.

NOTE: This script no longer writes any files. build.js reads .data files directly.
Run this script manually to see a human-readable summary in the terminal.
"""

import csv
import glob
import os
from collections import defaultdict
from datetime import datetime, timezone

REPO_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.path.join(REPO_ROOT, "token-usage")


def fmt(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(int(n))


def main():
    days_data = defaultdict(lambda: {
        "sessions": [],
        "total_tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0},
    })

    data_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.data")))
    if not data_files:
        print("No .data files found.")
        return

    for data_file in data_files:
        # Extract date from filename: YYYY-MM-DD_{hostname}-{os}.data -> YYYY-MM-DD
        basename = os.path.basename(data_file)
        date = basename.split('_')[0] if '_' in basename else os.path.splitext(basename)[0]
        try:
            with open(data_file, newline="") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    try:
                        tokens = {
                            "input": int(row.get("tokens_input", 0)),
                            "output": int(row.get("tokens_output", 0)),
                            "cache_read": int(row.get("tokens_cache_read", 0)),
                            "cache_creation": int(row.get("tokens_cache_creation", 0)),
                        }
                    except (ValueError, TypeError):
                        continue

                    model = row.get("model", "unknown")
                    project = row.get("project", "unknown")

                    day = days_data[date]
                    day["sessions"].append({
                        "session_id": row.get("session_id", ""),
                        "timestamp": row.get("timestamp", ""),
                        "project": project,
                        "model": model,
                        "tokens": tokens,
                        "duration_seconds": int(row.get("duration_seconds", 0) or 0),
                        "message_count": int(row.get("message_count", 0) or 0),
                    })
                    for key in ("input", "output", "cache_read", "cache_creation"):
                        day["total_tokens"][key] += tokens.get(key, 0)
        except (OSError, IOError):
            continue

    # Print summary
    days_list = []
    for date in sorted(days_data.keys()):
        day = days_data[date]
        days_list.append({
            "date": date,
            "session_count": len(day["sessions"]),
            "total_tokens": day["total_tokens"],
        })

    total_sessions = sum(d["session_count"] for d in days_list)
    total_tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    for d in days_list:
        for k in total_tokens:
            total_tokens[k] += d["total_tokens"][k]

    print(f"Aggregated {len(days_list)} days, {total_sessions} sessions")
    print(f"  Input:  {fmt(total_tokens['input'])}")
    print(f"  Output: {fmt(total_tokens['output'])}")
    print(f"  Cache:  {fmt(total_tokens['cache_read'])} read / {fmt(total_tokens['cache_creation'])} creation")
    print(f"  Total:  {fmt(sum(total_tokens.values()))}")


if __name__ == "__main__":
    main()
