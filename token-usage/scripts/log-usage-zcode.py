#!/usr/bin/env python3
"""ZCode Token Usage Tracker.

Reads session + model_usage from ~/.zcode/cli/db/db.sqlite, aggregates token
consumption per interactive session (subagent sessions are merged into their
parent via a recursive parent_id CTE), writes TSV records to
token-usage/YYYY-MM-DD_{hostname}-{os}.data, and performs auto git commit + push.

Usage:
  python3 log-usage-zcode.py                # scan all ZCode interactive sessions
  python3 log-usage-zcode.py --since 60     # scan sessions updated in last 60 minutes
  python3 log-usage-zcode.py --all          # force full scan (alias for no args)

When triggered by a ZCode Stop hook, reads session_id from stdin JSON or the
CLAUDE_SESSION_ID env var and records just that one session.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  配置区
# ═══════════════════════════════════════════════════════════════
REPO_DIR = Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))
ZCODE_DB = Path(os.environ.get("ZCODE_DB_PATH", str(Path.home() / ".zcode" / "cli" / "db" / "db.sqlite")))

# 节流:同一 session 在 THROTTLE_MINUTES 分钟内只记录一次(含 git 操作)。
# Stop hook 每轮都触发,但绝大多数应直接 return,避免频繁 commit + push。
# 兜底:即使节流期间崩溃,下次任何会话活动触发 --since 时仍会补录(因为 .data 里数据旧或缺失)。
THROTTLE_FILE = Path(os.environ.get("ZCODE_THROTTLE_FILE", str(Path.home() / ".zcode" / "tracker-throttle.json")))
THROTTLE_MINUTES = int(os.environ.get("ZCODE_THROTTLE_MINUTES", "15"))

CST = timezone(timedelta(hours=8))

SOURCE = "zcode"

# ── Deep session-log sink (shared with all agent trackers) ──
try:
    sys.path.insert(0, str(REPO_DIR / "token-usage" / "scripts"))
    from tracker_sink import TrackerSink  # noqa: E402

    sink = TrackerSink(source=SOURCE, repo_dir=REPO_DIR, log_prefix="[zcode]", branch_fallback="main")
except Exception:
    sink = None  # repo absent — nothing to record; main() will skip


def _skip() -> None:
    """Mirror the old graceful skip when the repo is absent."""
    try:
        with open(Path.home() / ".claude" / "hooks" / "tracker.log", "a") as f:
            f.write(f"SKIP: REPO_DIR not found ({REPO_DIR})\n")
    except Exception:
        pass


# ── 节流(statefile 记录每 session 最近一次记录时刻) ──────────

def is_throttled(session_id: str) -> bool:
    """True if this session was recorded less than THROTTLE_MINUTES ago."""
    if not THROTTLE_FILE.is_file():
        return False
    try:
        data = json.loads(THROTTLE_FILE.read_text(encoding="utf-8"))
        last = data.get(session_id, 0)
        return (time.time() - last) < THROTTLE_MINUTES * 60
    except (OSError, ValueError):
        return False


def mark_recorded(session_id: str) -> None:
    """Update throttle statefile with current timestamp for this session.

    Keeps only recent entries to avoid unbounded growth.
    """
    cutoff = time.time() - THROTTLE_MINUTES * 60 * 4  # 保留 4 倍窗口用于兜底补录判断
    data: dict = {}
    if THROTTLE_FILE.is_file():
        try:
            data = json.loads(THROTTLE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    # 清理过期条目
    data = {k: v for k, v in data.items() if v >= cutoff}
    data[session_id] = time.time()
    THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    THROTTLE_FILE.write_text(json.dumps(data), encoding="utf-8")


def get_git_branch(directory: str) -> str:
    """Run git branch --show-current in the given directory."""
    if not directory or not os.path.isdir(directory):
        return "main"
    return sink.git_branch(directory)


# ── SQLite helpers ────────────────────────────────────────────

def open_db() -> sqlite3.Connection:
    """Open ZCode DB read-only to avoid locking the live session."""
    uri = f"file:{ZCODE_DB}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# 递归 CTE:收集一个 interactive session 及其所有 subagent 后代。
# ZCode 把 subagent 作为独立 session 存储(parent_id 链回主会话),
# 归并子代理 token 才能得到会话的真实总消耗。
TREE_CTE = """
WITH RECURSIVE session_tree(id) AS (
    SELECT ?
    UNION ALL
    SELECT s.id FROM session s JOIN session_tree t ON s.parent_id = t.id
)
"""

AGGREGATE_SQL = (
    TREE_CTE
    + """
SELECT
    s.directory,
    s.time_created,
    COUNT(mu.id) AS request_count,
    COALESCE(SUM(mu.input_tokens), 0),
    COALESCE(SUM(mu.output_tokens), 0),
    COALESCE(SUM(mu.reasoning_tokens), 0),
    COALESCE(SUM(mu.cache_read_input_tokens), 0),
    COALESCE(SUM(mu.cache_creation_input_tokens), 0),
    MIN(mu.started_at),
    MAX(mu.completed_at)
FROM session s
LEFT JOIN model_usage mu
    ON mu.session_id IN (SELECT id FROM session_tree)
   AND mu.status = 'completed'
WHERE s.id = ?
GROUP BY s.id
"""
)

MODEL_SQL = (
    TREE_CTE
    + """
SELECT model_id
FROM model_usage
WHERE session_id IN (SELECT id FROM session_tree)
  AND status = 'completed'
  AND model_id IS NOT NULL
GROUP BY model_id
ORDER BY COUNT(*) DESC
LIMIT 1
"""
)

TURN_COUNT_SQL = (
    TREE_CTE
    + """
SELECT COUNT(*) FROM turn_usage WHERE session_id IN (SELECT id FROM session_tree)
"""
)


def query_session(conn: sqlite3.Connection, session_id: str) -> dict | None:
    """Aggregate token usage for an interactive session + its subagent tree."""
    cur = conn.cursor()
    row = cur.execute(AGGREGATE_SQL, (session_id, session_id)).fetchone()
    if row is None:
        return None

    request_count = row[2] or 0
    t_input = row[3] or 0
    t_output = row[4] or 0
    t_reasoning = row[5] or 0
    t_cache_read = row[6] or 0
    t_cache_creation = row[7] or 0
    min_started = row[8]
    max_completed = row[9]

    if request_count == 0:
        return None
    if t_input == 0 and t_output == 0:
        return None

    directory = row[0] or ""
    time_created = row[1] or 0

    model_row = cur.execute(MODEL_SQL, (session_id,)).fetchone()
    model = model_row[0] if model_row else "unknown"

    turn_row = cur.execute(TURN_COUNT_SQL, (session_id,)).fetchone()
    turn_count = turn_row[0] if turn_row else 0

    duration_seconds = 0
    if min_started and max_completed:
        duration_seconds = int((max_completed - min_started) / 1000)

    timestamp_cst = format_epoch_ms(time_created)
    date_str = timestamp_cst[:10]

    project = os.path.basename(directory) if directory else "unknown"
    git_branch = get_git_branch(directory)

    return {
        "session_id": session_id,
        "timestamp": timestamp_cst,
        "project": project,
        "model": model,
        "duration_seconds": duration_seconds,
        "message_count": turn_count,
        "tokens_input": t_input,
        "tokens_output": t_output,
        "tokens_cache_read": t_cache_read,
        "tokens_cache_creation": t_cache_creation,
        "git_branch": git_branch,
        "tokens_reasoning": t_reasoning,
        "_date": date_str,
    }


def format_epoch_ms(epoch_ms: int) -> str:
    """epoch ms -> ISO 8601 CST string 'YYYY-MM-DDTHH:MM:SS+08:00'."""
    if not epoch_ms:
        return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    try:
        dt = datetime.fromtimestamp(epoch_ms / 1000, tz=CST)
        return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except (ValueError, OSError):
        return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def list_interactive_sessions(conn: sqlite3.Connection, since_minutes: int | None) -> list[str]:
    """Return interactive session ids, optionally filtered by recent time_updated."""
    sql = "SELECT id FROM session WHERE task_type='interactive'"
    params: list = []
    if since_minutes is not None:
        cutoff_ms = int((time.time() - since_minutes * 60) * 1000)
        sql += " AND time_updated >= ?"
        params.append(cutoff_ms)
    sql += " ORDER BY time_updated DESC"
    cur = conn.cursor()
    rows = cur.execute(sql, params).fetchall()
    return [r[0] for r in rows]


# ── main ──────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Track ZCode token usage")
    parser.add_argument("--since", type=int, default=None,
                        help="Scan sessions updated in last N minutes")
    parser.add_argument("--all", action="store_true",
                        help="Force full scan of all interactive sessions")
    args = parser.parse_args()

    if sink is None:
        _skip()
        return
    if not REPO_DIR.is_dir():
        sink.log(f"SKIP: REPO_DIR not found ({REPO_DIR})")
        return

    if not ZCODE_DB.is_file():
        sink.log(f"SKIP: ZCode DB not found ({ZCODE_DB})")
        return

    # ── Resolve target session ids ──
    target_session_id: str | None = None

    # Stop hook payload on stdin (highest priority)
    hook_data = None
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read().strip()
            if raw:
                hook_data = json.loads(raw)
        except Exception:
            pass
    if hook_data and isinstance(hook_data, dict):
        sid = hook_data.get("session_id") or hook_data.get("conversationId") or hook_data.get("sessionId")
        if sid:
            target_session_id = sid
            sink.log(f"Hook payload received for session_id={sid[:12]}")

    # Fallback: CLAUDE_SESSION_ID env var (injected by ZCode hook runner)
    if not target_session_id:
        env_sid = os.environ.get("CLAUDE_SESSION_ID", "").strip()
        if env_sid:
            target_session_id = env_sid
            sink.log(f"Env var CLAUDE_SESSION_ID={env_sid[:12]}")

    # ── 节流:hook 触发的单会话路径,同 session N 分钟内不重复记录 ──
    # 仅对 hook 触发(target_session_id 来自 stdin/env 且无 --all/--since)生效;
    # --since / --all 是手动调用,始终全量执行(用于补录/排查)。
    manual = args.all or args.since is not None
    if target_session_id and not manual and is_throttled(target_session_id):
        sink.log(f"SKIP: session {target_session_id[:12]} throttled (< {THROTTLE_MINUTES}min)")
        return

    recorded = sink.recorded_sessions()
    conn = open_db()

    try:
        if target_session_id:
            session_ids = [target_session_id]
        else:
            session_ids = list_interactive_sessions(conn, args.since)
    except sqlite3.Error as e:
        sink.error_log(f"DB query failed: {e}")
        conn.close()
        return

    sink.log(f"START scanning {len(session_ids)} zcode sessions...")

    new_count = 0
    updated_count = 0
    changed_files: set[str] = set()

    for sid in session_ids:
        try:
            data = query_session(conn, sid)
        except sqlite3.Error as e:
            sink.error_log(f"query_session failed for {sid[:12]}: {e}")
            continue
        if not data:
            continue

        t_input = data["tokens_input"]
        t_output = data["tokens_output"]
        t_cache_read = data["tokens_cache_read"]
        t_cache_creation = data["tokens_cache_creation"]
        t_reasoning = data["tokens_reasoning"]

        # 节流:只要成功查到 session 数据就标记,后续 N 分钟内不再重复查询。
        # 即使 token 未变化也要标记 —— 这正是节流要覆盖的最常见场景
        # (会话活跃但自上次记录后无新对话)。
        mark_recorded(sid)

        if sid in recorded:
            old = recorded[sid]
            if (old["input"] == t_input and
                    old["output"] == t_output and
                    old["cache_read"] == t_cache_read and
                    old["cache_creation"] == t_cache_creation and
                    old["reasoning"] == t_reasoning):
                continue
            updated_count += 1
            sink.log(f"UPDATE session {sid[:12]} input={t_input} output={t_output}")
        else:
            new_count += 1
            sink.log(f"NEW session {sid[:12]} input={t_input} output={t_output}")

        date_str = data["_date"]
        changed_files.add(sink.upsert(data, date_str))

    conn.close()

    if new_count == 0 and updated_count == 0:
        sink.log("SKIP: no new or updated zcode sessions")
        return

    sink.log(f"Recorded: {new_count} new, {updated_count} updated sessions across {len(changed_files)} files")

    sink.git_sync(changed_files, f"track: zcode token usage ({new_count} new, {updated_count} updated)")

    sink.log("DONE zcode log-usage")


if __name__ == "__main__":
    main()