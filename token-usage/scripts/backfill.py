#!/usr/bin/env python3
"""Incremental backfill: scan Claude Code transcripts and merge into .data (TSV) files.

Key design: purely additive / update-by-session-id. Never deletes records.
  - New session_id → append
  - Existing session_id with different tokens → update that row (keep the higher one)
  - Existing session_id with same tokens → skip
  - Sessions from other machines (not found in local transcripts) → untouched
"""

import csv
import glob
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

CLAUDE_DIR = os.path.expanduser("~/.claude/projects")
# backfill.py is at token-usage/scripts/backfill.py, one level up is token-usage/
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
    """Resolve Claude project dir name to real filesystem path.

    Claude encodes paths as dashes: '-Users-saveole-projects-wx-java-codegen'
    means '/Users/saveole/projects/wx-java-codegen'.
    """
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


def token_total(tokens):
    """Sum all token fields for comparison."""
    if isinstance(tokens, dict):
        return tokens.get("input", 0) + tokens.get("output", 0) + \
               tokens.get("cache_read", 0) + tokens.get("cache_creation", 0)
    return 0


def load_existing_records():
    """Read all .data files, return {date: {session_id: {row_dict, raw_line}}}."""
    existing = defaultdict(dict)
    for data_file in glob.glob(os.path.join(DATA_DIR, "*.data")):
        date = os.path.splitext(os.path.basename(data_file))[0]
        try:
            with open(data_file, newline="") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    sid = row.get("session_id", "")
                    if sid:
                        existing[date][sid] = row
        except (OSError, IOError, csv.Error):
            pass
    return existing


def record_to_row(rec):
    """Convert a record dict to a TSV row string."""
    return (
        f"{rec['session_id']}\t{rec['timestamp']}\t{rec['project']}"
        f"\t{rec['model']}\t{rec['duration_seconds']}\t{rec['message_count']}"
        f"\t{rec['tokens']['input']}\t{rec['tokens']['output']}"
        f"\t{rec['tokens']['cache_read']}\t{rec['tokens']['cache_creation']}"
        f"\t{rec['git_branch']}"
    )


def write_data_file(date, records):
    """Write a complete .data file for a given date. records is {session_id: row_string}."""
    data_path = os.path.join(DATA_DIR, f"{date}.data")
    with open(data_path, "w") as f:
        f.write(TSV_HEADER + "\n")
        for sid in sorted(records.keys()):
            f.write(records[sid] + "\n")


def main():
    # Find all transcript JSONL files
    pattern = os.path.join(CLAUDE_DIR, "*", "*.jsonl")
    transcripts = sorted(glob.glob(pattern))
    print(f"Found {len(transcripts)} transcript files")

    # Load existing records: {date: {session_id: row_dict}}
    existing = load_existing_records()
    total_existing = sum(len(s) for s in existing.values())
    print(f"Existing records: {total_existing} sessions across {len(existing)} days")

    # Phase 1: scan transcripts, decide new/update/skip per session
    # Collect which dates need rewriting
    changed_dates = set()
    new_records = defaultdict(dict)   # date -> {session_id: record_dict}
    count_new = 0
    count_updated = 0
    count_same = 0
    count_empty = 0

    for i, transcript_path in enumerate(transcripts):
        record = process_transcript(transcript_path)

        if record is None:
            count_empty += 1
            continue

        session_id = record["session_id"]
        date = record["_date"]

        # Build TSV row for comparison
        new_row = record_to_row(record)
        new_total = token_total(record["tokens"])

        if date in existing and session_id in existing[date]:
            # Session exists — compare token totals
            old_row_dict = existing[date][session_id]
            old_total = token_total({
                "input": int(old_row_dict.get("tokens_input", 0)),
                "output": int(old_row_dict.get("tokens_output", 0)),
                "cache_read": int(old_row_dict.get("tokens_cache_read", 0)),
                "cache_creation": int(old_row_dict.get("tokens_cache_creation", 0)),
            })

            if new_total == old_total:
                count_same += 1
                continue
            else:
                # Update: transcript has different (usually more complete) data
                count_updated += 1
                changed_dates.add(date)
                new_records[date][session_id] = new_row
        else:
            # New session
            count_new += 1
            new_records[date][session_id] = new_row

        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(transcripts)}...")

    # Phase 2: merge and write
    total_written = 0
    all_affected_dates = set(new_records.keys()) | changed_dates

    for date in sorted(all_affected_dates):
        # Start with existing records for this date
        merged = {}
        if date in existing:
            for sid, row_dict in existing[date].items():
                merged[sid] = "\t".join(row_dict[col] for col in [
                    "session_id", "timestamp", "project", "model",
                    "duration_seconds", "message_count",
                    "tokens_input", "tokens_output", "tokens_cache_read",
                    "tokens_cache_creation", "git_branch",
                ])

        # Overlay with new/updated records
        for sid, row in new_records.get(date, {}).items():
            merged[sid] = row

        write_data_file(date, merged)
        total_written += len(new_records.get(date, {}))

    # Print results
    print(f"\nResults:")
    print(f"  New sessions:      {count_new}")
    print(f"  Updated sessions:  {count_updated}")
    print(f"  Unchanged:         {count_same}")
    print(f"  Empty/invalid:     {count_empty}")
    print(f"  Files rewritten:   {len(all_affected_dates)}")

    if all_affected_dates:
        dates = sorted(all_affected_dates)
        print(f"  Affected dates:    {dates[0]} ~ {dates[-1]}")

    # Run aggregate.py to print summary
    if count_new > 0 or count_updated > 0:
        print("\nRunning aggregate.py to print summary...")
        aggregate_script = os.path.join(DATA_DIR, "scripts", "aggregate.py")
        os.system(f"python3 {aggregate_script}")
    else:
        print("\nNo changes.")


if __name__ == "__main__":
    main()
