#!/usr/bin/env python3
"""OpenCode Token Usage Tracker — called from opencode plugin on session.updated events.

Reads pre-aggregated token data from ~/.local/share/opencode/opencode.db
(session table), writes TSV records to token-usage/YYYY-MM-DD_{hostname}-{os}.data,
then auto git commit + push.

Usage:
  python3 log-usage-opencode.py          # scan all sessions not yet recorded
  python3 log-usage-opencode.py --since MINUTES  # only sessions updated in last N minutes
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  配置区
# ═══════════════════════════════════════════════════════════════
REPO_DIR = Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))

OPENCODE_DB = Path(os.environ.get(
    "OPENCODE_DB_PATH",
    str(Path.home() / ".local" / "share" / "opencode" / "opencode.db"),
))

SOURCE = "opencode"

# ── Deep session-log sink (shared with all agent trackers) ──
try:
    sys.path.insert(0, str(REPO_DIR / "token-usage" / "scripts"))
    from tracker_sink import TrackerSink  # noqa: E402

    sink = TrackerSink(source=SOURCE, repo_dir=REPO_DIR)
except Exception:
    sink = None  # repo absent — nothing to record; main() will skip

CST = timezone(timedelta(hours=8))


def _skip() -> None:
    """Mirror the old graceful skip when the repo is absent."""
    try:
        with open(Path.home() / ".claude" / "hooks" / "tracker.log", "a") as f:
            f.write(f"SKIP: REPO_DIR not found ({REPO_DIR})\n")
    except Exception:
        pass


def get_git_branch(directory: str) -> str:
    """Run git branch --show-current in the given directory."""
    return sink.git_branch(directory)


def query_opencode_sessions(since_minutes: int | None = None) -> list[dict]:
    """Query opencode.db for sessions with token usage data."""
    if not OPENCODE_DB.is_file():
        sink.log(f"SKIP: opencode db not found at {OPENCODE_DB}")
        return []

    try:
        conn = sqlite3.connect(str(OPENCODE_DB))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        sink.error_log(f"Failed to connect opencode db: {e}")
        return []

    # Build query: sessions with non-zero tokens, joined with project name
    query = """
        SELECT
            s.id,
            s.title,
            s.directory,
            s.model,
            s.tokens_input,
            s.tokens_output,
            s.tokens_reasoning,
            s.tokens_cache_read,
            s.tokens_cache_write,
            s.cost,
            s.time_created,
            s.time_updated,
            p.name AS project_name,
            p.vcs
        FROM session s
        LEFT JOIN project p ON s.project_id = p.id
        WHERE (s.tokens_input > 0 OR s.tokens_output > 0)
    """
    params: list = []
    if since_minutes is not None:
        cutoff_ms = int((datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).timestamp() * 1000)
        query += " AND s.time_updated >= ?"
        params.append(cutoff_ms)

    query += " ORDER BY s.time_created DESC"

    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.Error as e:
        sink.error_log(f"Query failed: {e}")
        conn.close()
        return []

    sessions = []
    for row in rows:
        session_id = row["id"]
        # Count messages for this session
        msg_count = 0
        try:
            msg_count = conn.execute(
                "SELECT COUNT(*) FROM message WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
        except sqlite3.Error:
            pass

        # Parse model JSON (e.g. {"id":"deepseek-v4-pro","providerID":"deepseek"})
        model_id = "unknown"
        model_raw = row["model"]
        if model_raw:
            try:
                model_obj = json.loads(model_raw) if isinstance(model_raw, str) else model_raw
                model_id = model_obj.get("id", "unknown")
            except (json.JSONDecodeError, TypeError):
                model_id = str(model_raw)

        # duration in seconds
        duration = 0
        if row["time_created"] and row["time_updated"]:
            duration = max(0, int((row["time_updated"] - row["time_created"]) / 1000))

        # git branch
        directory = row["directory"] or ""
        git_branch = get_git_branch(directory)

        # project name: prefer DB project name, fallback to directory basename
        project = row["project_name"] or (os.path.basename(directory) if directory else "unknown")

        sessions.append({
            "session_id": session_id,
            "title": row["title"] or "",
            "model": model_id,
            "tokens_input": row["tokens_input"] or 0,
            "tokens_output": row["tokens_output"] or 0,
            "tokens_reasoning": row["tokens_reasoning"] or 0,
            "tokens_cache_read": row["tokens_cache_read"] or 0,
            "tokens_cache_creation": row["tokens_cache_write"] or 0,
            "cost": row["cost"] or 0,
            "duration": duration,
            "message_count": msg_count,
            "project": project,
            "git_branch": git_branch,
            "time_created": row["time_created"] or 0,
            "time_updated": row["time_updated"] or 0,
        })

    conn.close()
    return sessions


def main() -> None:
    if sink is None:
        _skip()
        return
    if not REPO_DIR.is_dir():
        sink.log(f"SKIP: REPO_DIR not found ({REPO_DIR})")
        return

    # Parse --since argument
    since_minutes = None
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--since":
        try:
            since_minutes = int(args[1])
        except ValueError:
            pass

    # Get existing opencode records for dedup
    recorded = sink.recorded_sessions()
    sink.log(f"START: found {len(recorded)} existing opencode records")

    # Query new sessions from opencode DB
    sessions = query_opencode_sessions(since_minutes=since_minutes)
    if not sessions:
        sink.log("DONE: no sessions found")
        return

    new_count = 0
    updated_count = 0
    changed_files: set[str] = set()

    for s in sessions:
        sid = s["session_id"]

        # Build timestamp
        if s["time_created"]:
            ts_dt = datetime.fromtimestamp(s["time_created"] / 1000, tz=timezone.utc)
            timestamp = ts_dt.astimezone(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")
            date = ts_dt.strftime("%Y-%m-%d")
        else:
            now = datetime.now(CST)
            timestamp = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            date = now.strftime("%Y-%m-%d")

        record = {
            "session_id": sid,
            "timestamp": timestamp,
            "project": s["project"],
            "model": s["model"],
            "duration_seconds": s["duration"],
            "message_count": s["message_count"],
            "tokens_input": s["tokens_input"],
            "tokens_output": s["tokens_output"],
            "tokens_cache_read": s["tokens_cache_read"],
            "tokens_cache_creation": s["tokens_cache_creation"],
            "git_branch": s["git_branch"],
            "tokens_reasoning": s["tokens_reasoning"],
        }

        # Dedup check
        if sid in recorded:
            new_tokens = {
                "input": s["tokens_input"],
                "output": s["tokens_output"],
                "cache_read": s["tokens_cache_read"],
                "cache_creation": s["tokens_cache_creation"],
                "reasoning": s["tokens_reasoning"],
            }
            if new_tokens == recorded[sid]:
                continue

        rel_path = sink.upsert(record, date)
        changed_files.add(rel_path)

        if sid in recorded:
            updated_count += 1
            sink.log(f"UPDATE: session {sid[:8]} token counts updated")
        else:
            new_count += 1
            sink.log(f"NEW: session {sid[:8]} input={s['tokens_input']} output={s['tokens_output']}")

    if not changed_files:
        sink.log("DONE: no changes")
        return

    sink.log(f"RECORDED: {new_count} new, {updated_count} updated sessions")

    sink.git_sync(changed_files, f"track: opencode token usage {new_count} new, {updated_count} updated")

    sink.log(f"DONE: {new_count} new, {updated_count} updated")


if __name__ == "__main__":
    main()