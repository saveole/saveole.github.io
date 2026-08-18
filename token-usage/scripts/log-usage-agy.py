#!/usr/bin/env python3
"""Antigravity CLI (agy) Token Usage Tracker.

Scans ~/.gemini/antigravity-cli/brain/ for agy session transcripts,
extracts token consumption & session metadata, writes TSV records to
token-usage/YYYY-MM-DD_{hostname}-{os}.data, and performs auto git commit + push.

Usage:
  python3 log-usage-agy.py          # scan all agy sessions not yet recorded
  python3 log-usage-agy.py --since 60  # scan sessions updated in last 60 minutes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  配置区
# ═══════════════════════════════════════════════════════════════
REPO_DIR = Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))
AGY_DIR = Path(os.environ.get("AGY_DIR_PATH", str(Path.home() / ".gemini" / "antigravity-cli")))

CST = timezone(timedelta(hours=8))

SOURCE = "agy"

# ── Deep session-log sink (shared with all agent trackers) ──
try:
    sys.path.insert(0, str(REPO_DIR / "token-usage" / "scripts"))
    from tracker_sink import TrackerSink  # noqa: E402

    sink = TrackerSink(source=SOURCE, repo_dir=REPO_DIR, log_prefix="[agy]", branch_fallback="main")
except Exception:
    sink = None  # repo absent — nothing to record; main() will skip


def _skip() -> None:
    """Mirror the old graceful skip when the repo is absent."""
    try:
        with open(Path.home() / ".claude" / "hooks" / "tracker.log", "a") as f:
            f.write(f"SKIP: REPO_DIR not found ({REPO_DIR})\n")
    except Exception:
        pass


def get_git_branch(directory: str) -> str:
    """Run git branch --show-current in the given directory."""
    if not directory or not os.path.isdir(directory):
        return "main"
    return sink.git_branch(directory)


def get_workspace_map() -> dict[str, str]:
    """Read ~/.gemini/antigravity-cli/history.jsonl to map cid to workspace path."""
    history_file = AGY_DIR / "history.jsonl"
    ws_map = {}
    if history_file.is_file():
        try:
            with open(history_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        cid = item.get("conversationId")
                        ws = item.get("workspace")
                        if cid and ws:
                            ws_map[cid] = ws
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            sink.error_log(f"Failed reading history.jsonl: {e}")
    return ws_map


def get_model_from_db(cid: str) -> str:
    """Read conversations/<cid>.db executor_metadata table for model name."""
    db_path = AGY_DIR / "conversations" / f"{cid}.db"
    if db_path.is_file():
        try:
            conn = sqlite3.connect(str(db_path))
            c = conn.cursor()
            c.execute("SELECT data FROM executor_metadata")
            rows = c.fetchall()
            conn.close()
            for r in rows:
                if r[0]:
                    s = r[0].decode("utf-8", errors="ignore")
                    m = re.search(r"(gemini-[\w\.-]+)", s)
                    if m:
                        return m.group(1)
        except Exception:
            pass
    return "gemini-3.6-flash"


def parse_agy_session(cid: str, workspace_map: dict[str, str]) -> dict | None:
    """Parse an agy session transcript in brain/<cid>/.system_generated/logs/."""
    brain_dir = AGY_DIR / "brain" / cid / ".system_generated" / "logs"
    transcript_path = brain_dir / "transcript_full.jsonl"
    if not transcript_path.is_file():
        transcript_path = brain_dir / "transcript.jsonl"
    if not transcript_path.is_file():
        return None

    input_chars = 0
    output_chars = 0
    thinking_chars = 0
    msg_count = 0
    timestamps: list[str] = []

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = entry.get("created_at")
                if ts:
                    timestamps.append(ts)

                src = entry.get("source", "")
                t = entry.get("type", "")
                content = entry.get("content", "")
                thinking = entry.get("thinking", "")

                if t == "USER_INPUT":
                    msg_count += 1
                    input_chars += len(content)
                elif src == "MODEL":
                    if t == "PLANNER_RESPONSE":
                        msg_count += 1
                        if content:
                            output_chars += len(content)
                        if thinking:
                            thinking_chars += len(thinking)
                        for tc in entry.get("tool_calls", []):
                            output_chars += len(json.dumps(tc))
                    else:
                        # Tool execution output returned to model
                        input_chars += len(content)
    except Exception as e:
        sink.error_log(f"Error reading transcript for {cid}: {e}")
        return None

    if msg_count == 0:
        return None

    tokens_input = int(input_chars * 0.35)
    tokens_output = int(output_chars * 0.35)
    tokens_reasoning = int(thinking_chars * 0.35)

    if tokens_input == 0 and tokens_output == 0:
        return None

    duration = 0
    if len(timestamps) >= 2:
        try:
            t0 = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            duration = int((t1 - t0).total_seconds())
        except (ValueError, TypeError):
            pass

    start_cst = datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    if timestamps:
        try:
            dt = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00")).astimezone(CST)
            start_cst = dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        except (ValueError, TypeError):
            pass

    ws = workspace_map.get(cid, str(REPO_DIR))
    project = os.path.basename(ws) if ws else "unknown"
    git_branch = get_git_branch(ws)
    model = get_model_from_db(cid)

    return {
        "session_id": cid,
        "timestamp": start_cst,
        "project": project,
        "model": model,
        "duration_seconds": duration,
        "message_count": msg_count,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "tokens_cache_read": 0,
        "tokens_cache_creation": 0,
        "git_branch": git_branch,
        "tokens_reasoning": tokens_reasoning,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Track agy token usage")
    parser.add_argument("--since", type=int, default=None, help="Scan sessions updated in last N minutes")
    args = parser.parse_args()

    if sink is None:
        _skip()
        return
    if not REPO_DIR.is_dir():
        sink.log(f"SKIP: REPO_DIR not found ({REPO_DIR})")
        return

    brain_base = AGY_DIR / "brain"
    if not brain_base.is_dir():
        sink.log(f"SKIP: agy brain dir not found at {brain_base}")
        return

    hook_data = None
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read().strip()
            if raw:
                hook_data = json.loads(raw)
        except Exception:
            pass

    recorded = sink.recorded_sessions()
    workspace_map = get_workspace_map()

    cids = []
    if hook_data and isinstance(hook_data, dict):
        cid = hook_data.get("conversationId") or hook_data.get("session_id")
        if cid:
            cids = [cid]
            sink.log(f"Hook payload received for conversationId={cid[:8]}")

    if not cids:
        cids = [d.name for d in brain_base.iterdir() if d.is_dir()]
        if args.since:
            now_ts = time.time()
            cutoff = now_ts - (args.since * 60)
            cids = [
                cid for cid in cids
                if (brain_base / cid).stat().st_mtime >= cutoff
            ]

    sink.log(f"START scanning {len(cids)} agy sessions...")

    new_count = 0
    updated_count = 0
    changed_files: set[str] = set()

    for cid in cids:
        data = parse_agy_session(cid, workspace_map)
        if not data:
            continue

        sid = data["session_id"]
        t_input = data["tokens_input"]
        t_output = data["tokens_output"]
        t_cache_read = data["tokens_cache_read"]
        t_cache_creation = data["tokens_cache_creation"]
        t_reasoning = data["tokens_reasoning"]

        # Check if already recorded with same tokens
        if sid in recorded:
            old_tokens = recorded[sid]
            if (old_tokens["input"] == t_input and
                old_tokens["output"] == t_output and
                old_tokens["cache_read"] == t_cache_read and
                old_tokens["cache_creation"] == t_cache_creation and
                old_tokens["reasoning"] == t_reasoning):
                continue
            updated_count += 1
            sink.log(f"UPDATE session {sid[:8]} input={t_input} output={t_output}")
        else:
            new_count += 1
            sink.log(f"NEW session {sid[:8]} input={t_input} output={t_output}")

        ts_str = data["timestamp"]
        try:
            dt = datetime.fromisoformat(ts_str)
            date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            date_str = datetime.now(CST).strftime("%Y-%m-%d")

        changed_files.add(sink.upsert(data, date_str))

    if new_count == 0 and updated_count == 0:
        sink.log("SKIP: no new or updated agy sessions")
        return

    sink.log(f"Recorded: {new_count} new, {updated_count} updated sessions across {len(changed_files)} files")

    sink.git_sync(changed_files, f"track: agy token usage ({new_count} new, {updated_count} updated)")

    sink.log("DONE agy log-usage")


if __name__ == "__main__":
    main()