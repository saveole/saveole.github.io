#!/usr/bin/env python3
"""pi coding agent Token Usage Tracker.

Reads pi session JSONL files (~/.pi/agent/sessions/**/*.jsonl), aggregates token
consumption per session (assistant usage + tool-embedded LLM usage + compaction /
branch-summary generation), writes TSV records to
token-usage/YYYY-MM-DD_{hostname}-{os}.data, and performs auto git commit + push.

pi 的优势:每条 assistant 消息直接携带 usage 字段
(input/output/cacheRead/cacheWrite/reasoning/totalTokens/cost),
无需像 Claude Code 那样解析嵌套结构,也无需像 agy 那样估算。

Usage:
  python3 log-usage-pi.py --session-file <path>  # hook 模式:单会话文件(节流)
  python3 log-usage-pi.py --since 60             # 扫描最近 N 分钟更新的会话
  python3 log-usage-pi.py --all                  # 全量扫描所有会话

由 pi 扩展(plugins/pi/index.ts)在 session_shutdown 时触发 hook 模式。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  配置区
# ═══════════════════════════════════════════════════════════════
REPO_DIR = Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))
PI_SESSION_DIR = Path(os.environ.get("PI_SESSION_DIR", str(Path.home() / ".pi" / "agent" / "sessions")))

# 节流:同一 session 在 THROTTLE_MINUTES 分钟内只记录一次(含 git 操作)。
# session_shutdown 在退出、/new、/resume、/fork、/clone 时都会触发,
# 节流避免频繁 commit + push。兜底:下次任何会话触发时,
# 因 .data 里数据过期或缺失,`--since` 全量补录仍会拉平。
THROTTLE_FILE = Path(os.environ.get("PI_THROTTLE_FILE", str(Path.home() / ".pi" / "tracker-throttle.json")))
THROTTLE_MINUTES = int(os.environ.get("PI_THROTTLE_MINUTES", "5"))

CST = timezone(timedelta(hours=8))

SOURCE = "pi"

# ── Deep session-log sink (shared with all agent trackers) ──
try:
    sys.path.insert(0, str(REPO_DIR / "token-usage" / "scripts"))
    from tracker_sink import TrackerSink  # noqa: E402

    sink = TrackerSink(source=SOURCE, repo_dir=REPO_DIR, log_prefix="[pi]", branch_fallback="main")
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
    """Update throttle statefile with current timestamp for this session."""
    cutoff = time.time() - THROTTLE_MINUTES * 60 * 4  # 保留 4 倍窗口用于兜底补录判断
    data: dict = {}
    if THROTTLE_FILE.is_file():
        try:
            data = json.loads(THROTTLE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    data = {k: v for k, v in data.items() if v >= cutoff}
    data[session_id] = time.time()
    THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    THROTTLE_FILE.write_text(json.dumps(data), encoding="utf-8")


def get_git_branch(directory: str) -> str:
    """Run git branch --show-current in the given directory."""
    if not directory or not os.path.isdir(directory):
        return "main"
    return sink.git_branch(directory)


# ── pi session JSONL parsing ──────────────────────────────────

def parse_session_file(path: Path) -> dict | None:
    """Parse a pi session JSONL file and aggregate token usage.

    pi 的 usage 字段:input / output / cacheRead / cacheWrite / reasoning /
    totalTokens / cost。统计范围与 pi footer 一致:
    - assistant 消息(每次 LLM 调用)
    - toolResult 消息内嵌 usage(工具内部调用的 LLM 工作)
    - compaction / branch_summary 条目的 usage(摘要生成)
    """
    session_id: str | None = None
    cwd: str | None = None
    start_ts: str | None = None
    model_counts: dict[str, int] = {}
    timestamps: list[datetime] = []
    assistant_count = 0

    t_input = t_output = t_cache_read = t_cache_creation = t_reasoning = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = entry.get("type")

            if etype == "session":
                session_id = entry.get("id") or session_id
                cwd = entry.get("cwd") or cwd
                start_ts = entry.get("timestamp") or start_ts
                continue

            usage: dict | None = None
            model: str = ""

            if etype == "message":
                msg = entry.get("message", {})
                role = msg.get("role")
                usage = msg.get("usage")
                if role == "assistant":
                    assistant_count += 1
                    model = msg.get("model", "")
                # toolResult 的 usage 表示工具内部执行的 LLM 工作,一并计入
            elif etype in ("compaction", "branch_summary"):
                usage = entry.get("usage")

            if not usage:
                continue

            t_input += usage.get("input", 0) or 0
            t_output += usage.get("output", 0) or 0
            t_cache_read += usage.get("cacheRead", 0) or 0
            t_cache_creation += usage.get("cacheWrite", 0) or 0
            t_reasoning += usage.get("reasoning", 0) or 0

            if model:
                model_counts[model] = model_counts.get(model, 0) + 1

            ts = entry.get("timestamp") or msg.get("timestamp") if etype == "message" else entry.get("timestamp")
            if ts:
                try:
                    timestamps.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
                except (ValueError, TypeError):
                    pass

    if assistant_count == 0:
        return None
    if t_input == 0 and t_output == 0:
        return None

    model = max(model_counts, key=model_counts.get) if model_counts else "unknown"

    duration = 0
    if len(timestamps) >= 2:
        duration = int((max(timestamps) - min(timestamps)).total_seconds())

    # session_id 兜底:从文件名取 uuid(时间戳_uuid.jsonl)
    if not session_id:
        session_id = path.stem.split("_", 1)[-1] if "_" in path.stem else path.stem

    timestamp_cst = parse_iso_cst(start_ts)
    date_str = timestamp_cst[:10]
    project = os.path.basename(cwd) if cwd else "unknown"
    git_branch = get_git_branch(cwd or "")

    return {
        "session_id": session_id,
        "timestamp": timestamp_cst,
        "project": project,
        "model": model,
        "duration_seconds": duration,
        "message_count": assistant_count,
        "tokens_input": t_input,
        "tokens_output": t_output,
        "tokens_cache_read": t_cache_read,
        "tokens_cache_creation": t_cache_creation,
        "git_branch": git_branch,
        "tokens_reasoning": t_reasoning,
        "_date": date_str,
    }


def parse_iso_cst(iso: str | None) -> str:
    """ISO 8601 -> 'YYYY-MM-DDTHH:MM:SS+08:00' (CST)."""
    if not iso:
        return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except (ValueError, TypeError, OSError):
        return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def list_session_files(since_minutes: int | None) -> list[Path]:
    """Enumerate pi session files, optionally filtered by recent mtime."""
    if not PI_SESSION_DIR.is_dir():
        return []
    files = sorted(PI_SESSION_DIR.glob("**/*.jsonl"))
    if since_minutes is not None:
        cutoff = time.time() - since_minutes * 60
        files = [f for f in files if f.stat().st_mtime >= cutoff]
    return files


# ── main ──────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Track pi coding agent token usage")
    parser.add_argument("--session-file", type=str, default=None,
                        help="Hook mode: process a single session JSONL file (throttled)")
    parser.add_argument("--since", type=int, default=None,
                        help="Scan sessions updated in last N minutes")
    parser.add_argument("--all", action="store_true",
                        help="Force full scan of all sessions")
    args = parser.parse_args()

    if sink is None:
        _skip()
        return
    if not REPO_DIR.is_dir():
        sink.log(f"SKIP: REPO_DIR not found ({REPO_DIR})")
        return

    if args.session_file:
        session_file = Path(args.session_file)
        if not session_file.is_file():
            sink.log(f"SKIP: session file not found ({session_file})")
            return

        # 节流:hook 模式的单会话路径,同 session N 分钟内不重复记录
        # (先读 header 拿 session_id,避免解析整个文件)
        session_id = None
        try:
            with open(session_file, encoding="utf-8") as f:
                first = f.readline()
            header = json.loads(first)
            session_id = header.get("id")
        except Exception:
            pass
        if session_id and is_throttled(session_id):
            sink.log(f"SKIP: session {session_id[:12]} throttled (< {THROTTLE_MINUTES}min)")
            return

        data = parse_session_file(session_file)
        if not data:
            sink.log(f"SKIP: no usable usage in {session_file.name}")
            return
        session_id = data["session_id"]
        mark_recorded(session_id)
        process_one(data)
        return

    # ── Sweep 模式(--since / --all / 无参数 = 全量) ──
    recorded = sink.recorded_sessions()
    files = list_session_files(args.since)
    sink.log(f"START scanning {len(files)} pi session files...")

    new_count = 0
    updated_count = 0
    changed_files: set[str] = set()

    for sf in files:
        try:
            data = parse_session_file(sf)
        except Exception as e:
            sink.error_log(f"parse failed for {sf.name}: {e}")
            continue
        if not data:
            continue

        sid = data["session_id"]
        mark_recorded(sid)

        t_input = data["tokens_input"]
        t_output = data["tokens_output"]
        t_cache_read = data["tokens_cache_read"]
        t_cache_creation = data["tokens_cache_creation"]
        t_reasoning = data["tokens_reasoning"]

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

        changed_files.add(sink.upsert(data, data["_date"]))

    if new_count == 0 and updated_count == 0:
        sink.log("SKIP: no new or updated pi sessions")
        return

    sink.log(f"Recorded: {new_count} new, {updated_count} updated sessions across {len(changed_files)} files")
    sink.git_sync(changed_files, f"track: pi token usage ({new_count} new, {updated_count} updated)")
    sink.log("DONE pi log-usage")


def process_one(data: dict) -> None:
    """Hook mode: upsert a single session record + git sync."""
    sid = data["session_id"]
    date_str = data["_date"]

    # 与 .data 已有记录比对:无变化则跳过(节流窗口过期后重查的场景)
    recorded = sink.recorded_sessions()
    new = sid not in recorded
    if not new:
        old = recorded[sid]
        if (old["input"] == data["tokens_input"] and
                old["output"] == data["tokens_output"] and
                old["cache_read"] == data["tokens_cache_read"] and
                old["cache_creation"] == data["tokens_cache_creation"] and
                old["reasoning"] == data["tokens_reasoning"]):
            sink.log(f"SKIP: session {sid[:12]} unchanged in .data")
            return
        sink.log(f"UPDATE session {sid[:12]} input={data['tokens_input']} output={data['tokens_output']}")
    else:
        sink.log(f"NEW session {sid[:12]} input={data['tokens_input']} output={data['tokens_output']}")

    rel_path = sink.upsert(data, date_str)
    sink.git_sync([rel_path], f"track: pi token usage ({1 if new else 0} new, {0 if new else 1} updated)")


if __name__ == "__main__":
    main()