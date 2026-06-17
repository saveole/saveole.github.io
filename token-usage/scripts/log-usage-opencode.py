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
import platform
import re
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  配置区
# ═══════════════════════════════════════════════════════════════
REPO_DIR = Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))

OPENCODE_DB = Path(os.environ.get(
    "OPENCODE_DB_PATH",
    str(Path.home() / ".local" / "share" / "opencode" / "opencode.db"),
))

DATA_DIR = REPO_DIR / "token-usage"
ERROR_LOG = Path.home() / ".claude" / "hooks" / "tracker-errors.log"
LOG_FILE = Path.home() / ".claude" / "hooks" / "tracker.log"

CST = timezone(timedelta(hours=8))

# Extended TSV header with reasoning tokens and source column
TSV_HEADER = "\t".join([
    "session_id", "timestamp", "project", "model",
    "duration_seconds", "message_count",
    "tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_creation",
    "git_branch", "tokens_reasoning", "source",
])

SOURCE = "opencode"


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")


def error_log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(ERROR_LOG, "a") as f:
        f.write(f"[{ts}] {msg}\n")


def run_git(*args: str) -> bool:
    """Run a git command; log stderr on failure. Returns True on success."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, timeout=120,
            cwd=str(REPO_DIR),
        )
        if result.returncode != 0:
            for line in result.stderr.strip().splitlines():
                if line:
                    error_log(line)
        return result.returncode == 0
    except Exception as e:
        error_log(str(e))
        return False


def get_git_branch(directory: str) -> str:
    """Run git branch --show-current in the given directory."""
    if not directory:
        return "unknown"
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=10,
            cwd=directory,
        )
        branch = result.stdout.strip()
        return branch if branch else "unknown"
    except Exception:
        return "unknown"


def get_recorded_sessions() -> dict[str, tuple[str, dict, str]]:
    """Scan all .data files for existing opencode session records.
    Returns {session_id: (data_file_path, tokens_dict, timestamp_str)}.
    """
    recorded: dict[str, tuple[str, dict, str]] = {}
    if not DATA_DIR.is_dir():
        return recorded
    for data_file in sorted(DATA_DIR.glob("*.data")):
        try:
            lines = data_file.read_text().splitlines()
            if len(lines) < 2:
                continue
            header_cols = lines[0].split("\t")
            for line in lines[1:]:
                if not line.strip():
                    continue
                cols = line.split("\t")
                sid = cols[0] if len(cols) > 0 else ""
                src = cols[12] if len(cols) > 12 else ""
                if sid and src == SOURCE:
                    tokens = {
                        "input": int(cols[6]) if len(cols) > 6 else 0,
                        "output": int(cols[7]) if len(cols) > 7 else 0,
                        "cache_read": int(cols[8]) if len(cols) > 8 else 0,
                        "cache_creation": int(cols[9]) if len(cols) > 9 else 0,
                        "reasoning": int(cols[11]) if len(cols) > 11 else 0,
                    }
                    ts = cols[1] if len(cols) > 1 else ""
                    recorded[sid] = (str(data_file), tokens, ts)
        except (OSError, ValueError):
            continue
    return recorded


def query_opencode_sessions(since_minutes: int | None = None) -> list[dict]:
    """Query opencode.db for sessions with token usage data."""
    if not OPENCODE_DB.is_file():
        log(f"SKIP: opencode db not found at {OPENCODE_DB}")
        return []

    try:
        conn = sqlite3.connect(str(OPENCODE_DB))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        error_log(f"Failed to connect opencode db: {e}")
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
        error_log(f"Query failed: {e}")
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


def write_tsv_record(session_id: str, record: str, date: str, hostname: str, os_name: str) -> str:
    """Write or update a TSV record. Returns the data file path."""
    data_file = DATA_DIR / f"{date}_{hostname}-{os_name}.data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if data_file.is_file():
        lines = data_file.read_text().splitlines(keepends=True)
        # Upgrade old 11-column header to 13-column if needed
        if lines and lines[0].count("\t") == 10:
            lines[0] = TSV_HEADER + "\n"
            # Pad existing rows to 13 columns
            for idx in range(1, len(lines)):
                if lines[idx].strip():
                    cols = lines[idx].rstrip("\n").split("\t")
                    while len(cols) < 13:
                        cols.append("0" if len(cols) < 12 else "claude")
                    lines[idx] = "\t".join(cols) + "\n"
        replaced = False
        new_lines: list[str] = []
        for line in lines:
            if line.startswith(session_id + "\t"):
                new_lines.append(record + "\n")
                replaced = True
            else:
                new_lines.append(line)
        if replaced:
            data_file.write_text("".join(new_lines))
        else:
            with open(data_file, "a") as f:
                f.write(record + "\n")
    else:
        with open(data_file, "w") as f:
            f.write(TSV_HEADER + "\n")
            f.write(record + "\n")

    return str(data_file.relative_to(REPO_DIR))


def main() -> None:
    if not REPO_DIR.is_dir():
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] SKIP: REPO_DIR not found ({REPO_DIR})\n")
        return

    # Parse --since argument
    since_minutes = None
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--since":
        try:
            since_minutes = int(args[1])
        except ValueError:
            pass

    hostname = socket.gethostname()
    os_name = platform.system()

    # Get existing opencode records for dedup
    recorded = get_recorded_sessions()
    log(f"START: found {len(recorded)} existing opencode records")

    # Query new sessions from opencode DB
    sessions = query_opencode_sessions(since_minutes=since_minutes)
    if not sessions:
        log("DONE: no sessions found")
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

        # Build TSV record
        record = "\t".join([
            sid,
            timestamp,
            s["project"],
            s["model"],
            str(s["duration"]),
            str(s["message_count"]),
            str(s["tokens_input"]),
            str(s["tokens_output"]),
            str(s["tokens_cache_read"]),
            str(s["tokens_cache_creation"]),
            s["git_branch"],
            str(s["tokens_reasoning"]),
            SOURCE,
        ])

        # Dedup check
        if sid in recorded:
            existing_tokens = recorded[sid][1]
            new_tokens = {
                "input": s["tokens_input"],
                "output": s["tokens_output"],
                "cache_read": s["tokens_cache_read"],
                "cache_creation": s["tokens_cache_creation"],
                "reasoning": s["tokens_reasoning"],
            }
            if new_tokens == existing_tokens:
                continue

        data_file_rel = write_tsv_record(sid, record, date, hostname, os_name)
        changed_files.add(data_file_rel)

        if sid in recorded:
            updated_count += 1
            log(f"UPDATE: session {sid[:8]} token counts updated")
        else:
            new_count += 1
            log(f"NEW: session {sid[:8]} input={s['tokens_input']} output={s['tokens_output']}")

    if not changed_files:
        log("DONE: no changes")
        return

    log(f"RECORDED: {new_count} new, {updated_count} updated sessions")

    # ── Git sync ──
    for f in changed_files:
        subprocess.run(
            ["git", "add", str(f)],
            capture_output=True, cwd=str(REPO_DIR),
        )

    if not run_git("commit", "-m", f"track: opencode token usage {new_count} new, {updated_count} updated"):
        log("GIT: commit FAILED (no changes or error)")

    if run_git("pull", "--rebase", "origin", "main"):
        log("GIT: pull OK")
    else:
        log("GIT: pull FAILED")

    if run_git("push", "origin", "main"):
        log("GIT: push OK")
    else:
        log("GIT: push FAILED")

    log(f"DONE: {new_count} new, {updated_count} updated")


if __name__ == "__main__":
    main()
