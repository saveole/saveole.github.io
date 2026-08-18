"""
token-usage plugin — Hermes session token tracker.

On session finalize, reads token stats from state.db and appends a TSV row
to the token-usage repo (same schema as Claude Code tracker), then auto-commits
and pushes to remote.

Hermes keeps its own lock, backfill, and a defensive stash-based git flow;
the TSV schema, dedup, and daily-file writing come from the shared
tracker_sink module.
"""

from __future__ import annotations

import logging
import os
import platform
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
REPO_DIR = Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))
LOCK_FILE = Path("/tmp/hermes-token-usage.lock")
STATE_DB = Path.home() / ".hermes" / "state.db"

SOURCE = "hermes"

# ── Deep session-log sink (shared with all agent trackers) ──
try:
    sys.path.insert(0, str(REPO_DIR / "token-usage" / "scripts"))
    from tracker_sink import TrackerSink, TSV_HEADER, _ALL_SOURCES  # noqa: E402

    sink = TrackerSink(
        source=SOURCE,
        repo_dir=REPO_DIR,
        log_file=Path.home() / ".hermes" / "plugins" / "token-usage-tracker.log",
        log_prefix="[hermes]",
    )
except Exception:
    sink = None  # repo absent — nothing to record; _record_usage will skip


def _log(msg: str) -> None:
    """Append to tracker log."""
    if sink is not None:
        sink.log(msg)


def _get_session_data(session_id: str) -> Optional[Dict[str, Any]]:
    """Read session token stats + project from Hermes state.db in one query."""
    if not STATE_DB.exists():
        _log("SKIP: state.db not found")
        return None

    try:
        conn = sqlite3.connect(str(STATE_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT id, model, started_at, ended_at, end_reason,
                   message_count, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens,
                   reasoning_tokens, title, cwd, git_branch
            FROM sessions WHERE id = ?
            """,
            (session_id,),
        )
        row = cur.fetchone()
        conn.close()
    except Exception as exc:
        _log(f"SKIP: state.db query failed: {exc}")
        return None

    if not row:
        _log(f"SKIP: session {session_id[:8]} not found in state.db")
        return None

    d = dict(row)
    # Skip zero-token sessions
    if d["input_tokens"] == 0 and d["output_tokens"] == 0:
        _log(f"SKIP: session {session_id[:8]} has zero tokens")
        return None

    # Compute duration
    duration = 0
    if d["started_at"] and d["ended_at"]:
        duration = int(d["ended_at"] - d["started_at"])

    # Determine project: db cwd > title > unknown
    project = d.get("cwd") or ""
    if project and project != "/":
        project = os.path.basename(project.rstrip("/"))
    if not project:
        project = d.get("title") or ""
    if not project:
        try:
            cwd = os.getcwd()
            if cwd and cwd != "/":
                project = os.path.basename(cwd)
        except Exception:
            pass
    if not project:
        project = "unknown"

    # Git branch: db value > live git command
    git_branch = d.get("git_branch") or ""
    if not git_branch:
        git_branch = _get_git_branch()

    return {
        "session_id": d["id"],
        "model": d["model"] or "unknown",
        "duration_seconds": duration,
        "message_count": d["message_count"] or 0,
        "tokens_input": d["input_tokens"] or 0,
        "tokens_output": d["output_tokens"] or 0,
        "tokens_cache_read": d["cache_read_tokens"] or 0,
        "tokens_cache_creation": d["cache_write_tokens"] or 0,
        "tokens_reasoning": d["reasoning_tokens"] or 0,
        "project": project,
        "git_branch": git_branch,
    }


def _get_git_branch() -> str:
    """Get current git branch."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _acquire_lock() -> bool:
    """Non-blocking file lock via mkdir."""
    lock_dir = Path("/tmp/hermes-token-usage.lockdir")
    try:
        lock_dir.mkdir(exist_ok=False)
        return True
    except FileExistsError:
        return False


def _release_lock() -> None:
    """Release the lock."""
    try:
        Path("/tmp/hermes-token-usage.lockdir").rmdir()
    except Exception:
        pass


def _git(data_file: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command in REPO_DIR."""
    return subprocess.run(
        ["git", "-C", str(REPO_DIR)] + list(args),
        capture_output=True, text=True, timeout=timeout,
    )


def _git_sync(data_file: Path) -> None:
    """git add + commit (fast, local), then async push in background."""
    if not (REPO_DIR / ".git").exists():
        _log("SKIP: REPO_DIR is not a git repo")
        return

    rel_path = data_file.relative_to(REPO_DIR)

    # 0. Stash any unstaged changes so pull --rebase won't fail
    _git(data_file, "stash", "--include-untracked")

    # 1. Pull latest to avoid diverged branches
    t0 = time.monotonic()
    _log("GIT: pulling origin main...")
    r = _git(data_file, "pull", "--rebase", "origin", "main")
    elapsed = time.monotonic() - t0
    if r.returncode != 0:
        _log(f"GIT pull FAILED ({elapsed:.1f}s): {r.stderr.strip()[:200]}")
    else:
        _log(f"GIT: pull OK ({elapsed:.1f}s)")

    # Restore stashed changes (if any)
    _git(data_file, "stash", "pop")

    # 2. Stage the data file
    r = _git(data_file, "add", str(rel_path))
    if r.returncode != 0:
        _log(f"GIT add FAILED: {r.stderr.strip()[:200]}")
        return

    # 3. Check if there are staged changes
    r = _git(data_file, "diff", "--cached", "--quiet")
    if r.returncode == 0:
        _log("GIT: no changes to commit")
        return

    # 4. Commit (local, fast)
    t0 = time.monotonic()
    _log("GIT: committing...")
    r = _git(data_file, "commit", "-m", f"track: hermes token usage {data_file.stem}")
    elapsed = time.monotonic() - t0
    if r.returncode != 0:
        _log(f"GIT commit FAILED ({elapsed:.1f}s): {r.stderr.strip()[:200]}")
        return

    _log(f"GIT: committed OK ({elapsed:.1f}s)")

    # 5. Push in background — don't block session exit
    t0 = time.monotonic()
    _log("GIT: pushing origin main...")
    try:
        r = _git(data_file, "push", "origin", "main", timeout=60)
        elapsed = time.monotonic() - t0
        if r.returncode == 0:
            _log(f"GIT: push OK ({elapsed:.1f}s)")
        else:
            _log(f"GIT push FAILED ({elapsed:.1f}s): {r.stderr.strip()[:200]}")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        _log(f"GIT push error ({elapsed:.1f}s): {exc}")


def _backfill_missing() -> int:
    """Scan state.db for all sessions, append any not yet recorded in .data files.

    Returns count of newly backfilled sessions.
    Only appends — never modifies existing records. No git operations.
    """
    if sink is None or not STATE_DB.exists() or not sink.data_dir.exists():
        return 0

    # 1. Collect already-recorded session_ids from .data files (all sources)
    recorded = set(sink.recorded_sessions(source=_ALL_SOURCES))

    # 2. Query all non-zero sessions from state.db
    try:
        conn = sqlite3.connect(str(STATE_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT id, model, started_at, ended_at,
                   message_count, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens,
                   reasoning_tokens, title, cwd, git_branch
            FROM sessions
            WHERE input_tokens > 0 OR output_tokens > 0
            """
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        _log(f"BACKFILL: state.db query failed: {exc}")
        return 0

    # 3. Find unrecorded sessions, group by date
    new_by_date = {}  # {date_str: [tsv_row, ...]}

    for row in rows:
        sid = row["id"]
        if sid in recorded:
            continue

        duration = 0
        if row["started_at"] and row["ended_at"]:
            duration = int(row["ended_at"] - row["started_at"])

        project = row["cwd"] or ""
        if project and project != "/":
            project = os.path.basename(project.rstrip("/"))
        if not project:
            project = row["title"] or "unknown"
        model = row["model"] or "unknown"

        git_branch = row["git_branch"] or "unknown"

        if row["started_at"]:
            try:
                dt = datetime.fromtimestamp(row["started_at"], tz=timezone(timedelta(hours=8)))
            except Exception:
                dt = None
        else:
            dt = None

        record = {
            "session_id": sid,
            "timestamp": dt.strftime("%Y-%m-%dT%H:%M:%S+08:00") if dt else datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "project": project,
            "model": model,
            "duration_seconds": duration,
            "message_count": row["message_count"] or 0,
            "tokens_input": row["input_tokens"] or 0,
            "tokens_output": row["output_tokens"] or 0,
            "tokens_cache_read": row["cache_read_tokens"] or 0,
            "tokens_cache_creation": row["cache_write_tokens"] or 0,
            "git_branch": git_branch,
            "tokens_reasoning": row["reasoning_tokens"] or 0,
        }
        date_str = record["timestamp"][:10]

        if date_str not in new_by_date:
            new_by_date[date_str] = []
        new_by_date[date_str].append(sink.format_row(record))

    if not new_by_date:
        return 0

    # 4. Append new records
    total = 0
    for date_str, rows_list in sorted(new_by_date.items()):
        data_file = sink.data_dir / f"{date_str}_{platform.node() or 'unknown'}-{platform.system() or 'unknown'}.data"

        # Double-check for race with concurrent writes
        if data_file.exists():
            existing = data_file.read_text()
            rows_list = [r for r in rows_list if r.split("\t", 1)[0] not in existing]
            if not rows_list:
                continue

        if not data_file.exists():
            data_file.write_text(TSV_HEADER + "\n")
        with open(data_file, "a") as f:
            for r in rows_list:
                f.write(r + "\n")
                total += 1

    if total:
        _log(f"BACKFILL: {total} missing sessions appended")
    return total


def _record_usage(session_id: str, platform_name: str) -> None:
    """Main logic: read session data, write TSV, git sync, then backfill missing sessions."""
    _log(f"START session={session_id[:8] if session_id else 'None'} platform={platform_name}")

    if not session_id:
        _log("SKIP: no session_id")
        return

    if sink is None:
        _log(f"SKIP: REPO_DIR not found ({REPO_DIR})")
        return

    if not REPO_DIR.exists():
        _log(f"SKIP: REPO_DIR not found ({REPO_DIR})")
        return

    # Get session data from state.db (single query, includes project)
    data = _get_session_data(session_id)
    if not data:
        return

    _log(
        f"TOKENS input={data['tokens_input']} output={data['tokens_output']} "
        f"cache_read={data['tokens_cache_read']} cache_creation={data['tokens_cache_creation']} "
        f"reasoning={data['tokens_reasoning']}"
    )

    # Build record
    now = datetime.now(timezone(timedelta(hours=8)))
    record = {
        "session_id": data["session_id"],
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "project": data["project"],
        "model": data["model"],
        "duration_seconds": data["duration_seconds"],
        "message_count": data["message_count"],
        "tokens_input": data["tokens_input"],
        "tokens_output": data["tokens_output"],
        "tokens_cache_read": data["tokens_cache_read"],
        "tokens_cache_creation": data["tokens_cache_creation"],
        "git_branch": data["git_branch"],
        "tokens_reasoning": data["tokens_reasoning"],
    }
    date_str = now.strftime("%Y-%m-%d")

    # Concurrency lock
    if not _acquire_lock():
        _log("SKIP: could not acquire lock")
        return

    try:
        # Deduplicate by session_id (exact match, source-filtered)
        if data["session_id"] in sink.recorded_sessions():
            _log(f"SKIP: session {session_id[:8]} already recorded")
            return

        # Write TSV (shared sink: header + filename + append)
        rel_path = sink.upsert(record, date_str)
        _log(f"WROTE: {rel_path}")
        data_file = sink.data_dir / Path(rel_path).name

        # Git sync (commit is sync, push is async)
        _git_sync(data_file)

        # Backfill any missing sessions from state.db (no git, append-only)
        try:
            _backfill_missing()
        except Exception as exc:
            _log(f"BACKFILL error: {exc}")

    except Exception as exc:
        _log(f"ERROR: {exc}")
    finally:
        _release_lock()


def register(ctx) -> None:
    """Plugin entry point — register on_session_finalize hook."""

    def on_session_finalize(session_id: str = None, platform: str = "cli", **kwargs):
        try:
            _record_usage(session_id or "", platform or "cli")
        except Exception as exc:
            _log(f"FATAL: unhandled error: {exc}")

    ctx.register_hook("on_session_finalize", on_session_finalize)
    logger.info("token-usage plugin registered (on_session_finalize)")