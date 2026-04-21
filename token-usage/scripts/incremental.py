#!/usr/bin/env python3
"""Lightweight incremental backfill: scan Claude Code transcripts, append missing sessions.

Designed to be called by log-usage.sh in background after each session ends.
No git operations — the hook already handles git.
Only appends new sessions; never modifies existing records.
"""

import csv
import glob
import json
import os
import platform
import sys
from collections import Counter
from datetime import datetime, timezone

CLAUDE_DIR = os.path.expanduser("~/.claude/projects")
# incremental.py is at token-usage/scripts/incremental.py
DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TSV_HEADER = (
    "session_id\ttimestamp\tproject\tmodel\tduration_seconds\tmessage_count"
    "\ttokens_input\ttokens_output\ttokens_cache_read"
    "\ttokens_cache_creation\tgit_branch"
)


def parse_ts(ts_str):
    """Parse ISO timestamp to datetime (UTC)."""
    if not ts_str:
        return None
    try:
        cleaned = ts_str.rstrip("Z").split(".")[0]
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def resolve_project(dir_name):
    """Resolve Claude project dir name to real filesystem path."""
    home = os.path.expanduser("~")
    encoded = dir_name.lstrip("-")
    parts = encoded.split("-")

    if len(parts) >= 2 and parts[0] == "Users":
        remaining = parts[2:]
    else:
        remaining = parts

    if not remaining:
        return home, "unknown"

    path = home
    i = 0
    while i < len(remaining):
        found = False
        for j in range(len(remaining), i, -1):
            candidate_name = "-".join(remaining[i:j])
            candidate_path = os.path.join(path, candidate_name)
            if os.path.isdir(candidate_path):
                path = candidate_path
                i = j
                found = True
                break
        if not found:
            i += 1

    name = os.path.basename(path) if path != home else "unknown"
    return path, name


def process_transcript(transcript_path):
    """Parse a transcript JSONL file and extract a usage record.

    Mirrors log-usage.sh: deduplicate by message.id, sum token fields.
    Returns dict or None.
    """
    seen_ids = set()
    last_usage = {}
    tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    model_counts = Counter()
    timestamps = []
    msg_count = 0
    git_branch = None

    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") != "assistant":
                    continue

                msg = entry.get("message", {})
                msg_id = msg.get("id")

                if msg_id:
                    if msg_id in seen_ids:
                        prev = last_usage.get(msg_id)
                        if prev:
                            tokens["input"] -= prev.get("input_tokens", 0)
                            tokens["output"] -= prev.get("output_tokens", 0)
                            tokens["cache_read"] -= prev.get("cache_read_input_tokens", 0)
                            tokens["cache_creation"] -= prev.get("cache_creation_input_tokens", 0)
                    else:
                        seen_ids.add(msg_id)

                    usage = msg.get("usage", {})
                    last_usage[msg_id] = usage

                    tokens["input"] += usage.get("input_tokens", 0)
                    tokens["output"] += usage.get("output_tokens", 0)
                    tokens["cache_read"] += usage.get("cache_read_input_tokens", 0)
                    tokens["cache_creation"] += usage.get("cache_creation_input_tokens", 0)
                else:
                    usage = msg.get("usage", {})
                    tokens["input"] += usage.get("input_tokens", 0)
                    tokens["output"] += usage.get("output_tokens", 0)
                    tokens["cache_read"] += usage.get("cache_read_input_tokens", 0)
                    tokens["cache_creation"] += usage.get("cache_creation_input_tokens", 0)

                model = msg.get("model")
                if model:
                    model_counts[model] += 1

                ts = entry.get("timestamp")
                if ts:
                    timestamps.append(ts)

                if not git_branch:
                    git_branch = entry.get("gitBranch")

                msg_count += 1
    except (OSError, IOError):
        return None

    if tokens["input"] == 0 and tokens["output"] == 0:
        return None

    if not timestamps:
        return None

    model = model_counts.most_common(1)[0][0] if model_counts else "unknown"

    timestamps.sort()
    first_ts = timestamps[0]
    last_ts = timestamps[-1]

    t1 = parse_ts(first_ts)
    t2 = parse_ts(last_ts)
    duration = int((t2 - t1).total_seconds()) if t1 and t2 else 0

    timestamp = first_ts[:19] + "Z" if not first_ts.endswith("Z") else first_ts
    date = first_ts[:10]

    dir_name = os.path.basename(os.path.dirname(transcript_path))
    _, proj_name = resolve_project(dir_name)

    return {
        "session_id": os.path.splitext(os.path.basename(transcript_path))[0],
        "timestamp": timestamp,
        "project": proj_name,
        "model": model,
        "duration_seconds": duration,
        "message_count": msg_count,
        "tokens": tokens,
        "git_branch": git_branch or "unknown",
        "_date": date,
    }


def load_recorded_session_ids():
    """Scan all .data files, return set of already-recorded session_ids."""
    recorded = set()
    for data_file in glob.glob(os.path.join(DATA_DIR, "*.data")):
        try:
            with open(data_file, newline="") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    sid = row.get("session_id", "")
                    if sid:
                        recorded.add(sid)
        except (OSError, IOError, csv.Error):
            pass
    return recorded


def main():
    hostname = platform.node() or "unknown"
    os_name = platform.system() or "unknown"

    # Phase 1: collect all already-recorded session_ids (fast set lookup)
    recorded = load_recorded_session_ids()

    # Phase 2: scan transcripts, find unrecorded sessions
    pattern = os.path.join(CLAUDE_DIR, "*", "*.jsonl")
    transcripts = sorted(glob.glob(pattern))

    # Group new records by date
    # {date: [tsv_row_string, ...]}
    new_by_date = {}

    for transcript_path in transcripts:
        session_id = os.path.splitext(os.path.basename(transcript_path))[0]
        if session_id in recorded:
            continue

        record = process_transcript(transcript_path)
        if record is None:
            continue

        date = record["_date"]
        row = (
            f"{record['session_id']}\t{record['timestamp']}\t{record['project']}"
            f"\t{record['model']}\t{record['duration_seconds']}\t{record['message_count']}"
            f"\t{record['tokens']['input']}\t{record['tokens']['output']}"
            f"\t{record['tokens']['cache_read']}\t{record['tokens']['cache_creation']}"
            f"\t{record['git_branch']}"
        )

        if date not in new_by_date:
            new_by_date[date] = []
        new_by_date[date].append(row)

    if not new_by_date:
        return

    # Phase 3: append new records to per-date files
    total_new = 0
    for date in sorted(new_by_date.keys()):
        data_file = os.path.join(DATA_DIR, f"{date}_{hostname}-{os_name}.data")

        # Ensure header exists
        if not os.path.exists(data_file):
            with open(data_file, "w") as f:
                f.write(TSV_HEADER + "\n")

        # Append new rows
        with open(data_file, "a") as f:
            for row in new_by_date[date]:
                f.write(row + "\n")
                total_new += 1

    print(f"incremental: {total_new} new sessions backfilled")


if __name__ == "__main__":
    main()
