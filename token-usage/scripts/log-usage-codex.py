#!/usr/bin/env python3
"""Codex CLI Token Usage Tracker.

Reads Codex CLI session rollouts (~/.codex/sessions/**/rollout-*.jsonl),
aggregates token consumption from `event_msg` token_count events, writes TSV
records to token-usage/YYYY-MM-DD_{hostname}-{os}.data, then auto git
commit + push.

Codex CLI 以 rollout JSONL 保存每个会话,相关事件:
- session_meta: 会话 id / 开始时间 / cwd / git 分支 / cli_version / model_provider
- event_msg (payload.type == "token_count"): info.total_token_usage 为累计用量,
  包含 input_tokens / cached_input_tokens / cache_write_input_tokens /
  output_tokens / reasoning_output_tokens / total_tokens。
  token_count 每次都是累计值,取最后一次即为会话最终用量。

注意:token_count 事件从较新的 codex-cli 版本开始写入,更早的 rollout 没有
usage 数据,脚本会跳过并记日志(SKIP: no usage)。

Usage:
  python3 log-usage-codex.py --since 60   # 扫描最近 N 分钟更新的会话
  python3 log-usage-codex.py --all        # 全量扫描所有会话(默认)
  python3 log-usage-codex.py --rollout <path>  # 单文件处理(配合 wrapper / notify)
  python3 log-usage-codex.py --dry-run    # 只打印将写入的记录,不写文件不碰 git
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  配置区
# ═══════════════════════════════════════════════════════════════
REPO_DIR = Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))
CODEX_SESSION_DIR = Path(os.environ.get("CODEX_SESSION_DIR", str(Path.home() / ".codex" / "sessions")))

# 节流:单文件模式(--rollout)下,同一 session 在 THROTTLE_MINUTES 分钟内只记录一次。
# Codex 的 notify 机制可能多次触发,节流避免频繁 commit + push;
# 兜底:下次全量/--since 扫描时,因 .data 里数据过期或缺失仍会补录。
THROTTLE_FILE = Path(os.environ.get("CODEX_THROTTLE_FILE", str(Path.home() / ".codex" / "tracker-throttle.json")))
THROTTLE_MINUTES = int(os.environ.get("CODEX_THROTTLE_MINUTES", "5"))

CST = timezone(timedelta(hours=8))

SOURCE = "codex"

# ── Deep session-log sink (shared with all agent trackers) ──
try:
    sys.path.insert(0, str(REPO_DIR / "token-usage" / "scripts"))
    from tracker_sink import TrackerSink  # noqa: E402

    sink = TrackerSink(source=SOURCE, repo_dir=REPO_DIR, log_prefix="[codex]")
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
        return "unknown"
    return sink.git_branch(directory)


def parse_iso_cst(iso: str | None) -> str:
    """ISO 8601 -> 'YYYY-MM-DDTHH:MM:SS+08:00' (CST)."""
    if not iso:
        return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    except (ValueError, TypeError, OSError):
        return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def parse_iso_dt(iso: str | None) -> datetime | None:
    """ISO 8601 -> aware datetime (or None on failure)."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError):
        return None


# ── Codex rollout JSONL parsing ───────────────────────────────

def parse_rollout(path: Path) -> dict | None:
    """Parse a Codex session rollout JSONL and aggregate token usage.

    - session_meta: session_id / start time / cwd / git branch
    - event_msg token_count: cumulative total_token_usage (take the last one)
    - model: most frequent model id from turn_context / response_item payloads
    - message_count: assistant response_item messages
    """
    session_id: str | None = None
    start_ts: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    model_provider: str | None = None
    model_counts: Counter[str] = Counter()
    assistant_count = 0

    usage: dict | None = None
    last_event_ts: datetime | None = None

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = parse_iso_dt(entry.get("timestamp"))
            if ts and (last_event_ts is None or ts > last_event_ts):
                last_event_ts = ts

            etype = entry.get("type")

            if etype == "session_meta":
                payload = entry.get("payload", {}) or {}
                session_id = payload.get("session_id") or payload.get("id") or session_id
                start_ts = payload.get("timestamp") or start_ts
                cwd = payload.get("cwd") or cwd
                model_provider = payload.get("model_provider") or model_provider
                git_info = payload.get("git") or {}
                if isinstance(git_info, dict) and git_info.get("branch"):
                    git_branch = git_info["branch"]
                continue

            payload = entry.get("payload", {}) or {}

            # token_count 事件:total_token_usage 为累计值,直接取最后一次
            if etype == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                total = info.get("total_token_usage") or {}
                if total:
                    usage = total
                continue

            # 模型名:turn_context / response_item 都带 model 字段
            model = payload.get("model")
            if isinstance(model, str) and model:
                model_counts[model] += 1

            # assistant 消息数:与 Claude Code / pi 的 message_count 语义一致
            if etype == "response_item" and payload.get("type") == "message":
                if payload.get("role") == "assistant":
                    assistant_count += 1

    if not usage:
        return None

    input_tokens = int(usage.get("input_tokens", 0) or 0)
    cached_input = int(usage.get("cached_input_tokens", 0) or 0)
    cache_write = int(usage.get("cache_write_input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    reasoning = int(usage.get("reasoning_output_tokens", 0) or 0)

    if input_tokens == 0 and output_tokens == 0:
        return None

    # session_id 兜底:文件名 rollout-<ts>-<uuid>.jsonl 的最后一个段
    if not session_id:
        stem = path.stem
        parts = stem.split("-")
        session_id = parts[-1] if len(parts) >= 2 else stem

    # input_tokens 含缓存部分,拆分为 新输入 + cache_read,与 Claude Code 语义一致
    uncached_input = max(0, input_tokens - cached_input)

    model = model_counts.most_common(1)[0][0] if model_counts else (model_provider or "unknown")

    start_dt = parse_iso_dt(start_ts)
    duration = 0
    if start_dt and last_event_ts and last_event_ts > start_dt:
        duration = int((last_event_ts - start_dt).total_seconds())

    timestamp_cst = parse_iso_cst(start_ts)
    date_str = timestamp_cst[:10]
    project = os.path.basename(cwd) if cwd else "unknown"
    if not git_branch:
        git_branch = get_git_branch(cwd or "")

    return {
        "session_id": session_id,
        "timestamp": timestamp_cst,
        "project": project,
        "model": model,
        "duration_seconds": duration,
        "message_count": assistant_count,
        "tokens_input": uncached_input,
        "tokens_output": output_tokens,
        "tokens_cache_read": cached_input,
        "tokens_cache_creation": cache_write,
        "git_branch": git_branch,
        "tokens_reasoning": reasoning,
        "_date": date_str,
    }


def list_rollout_files(since_minutes: int | None) -> list[Path]:
    """Enumerate Codex rollout files, optionally filtered by recent mtime."""
    if not CODEX_SESSION_DIR.is_dir():
        return []
    files = sorted(CODEX_SESSION_DIR.glob("**/*.jsonl"))
    if since_minutes is not None:
        cutoff = time.time() - since_minutes * 60
        files = [f for f in files if f.stat().st_mtime >= cutoff]
    return files


# ── main ──────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Track Codex CLI token usage")
    parser.add_argument("--rollout", type=str, default=None,
                        help="Hook mode: process a single rollout JSONL file (throttled)")
    parser.add_argument("--since", type=int, default=None,
                        help="Scan sessions updated in last N minutes")
    parser.add_argument("--all", action="store_true",
                        help="Force full scan of all sessions")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned records without writing files or touching git")
    args = parser.parse_args()

    if sink is None:
        _skip()
        return
    if not REPO_DIR.is_dir():
        sink.log(f"SKIP: REPO_DIR not found ({REPO_DIR})")
        return

    if args.rollout:
        rollout_file = Path(args.rollout)
        if not rollout_file.is_file():
            sink.log(f"SKIP: rollout file not found ({rollout_file})")
            return

        # 节流:单文件路径,同 session N 分钟内不重复记录
        session_id = None
        try:
            with open(rollout_file, encoding="utf-8") as f:
                first = f.readline()
            header = json.loads(first)
            payload = header.get("payload", {}) or {}
            session_id = payload.get("session_id") or payload.get("id")
        except Exception:
            pass
        if session_id and is_throttled(session_id):
            sink.log(f"SKIP: session {session_id[:12]} throttled (< {THROTTLE_MINUTES}min)")
            return

        data = parse_rollout(rollout_file)
        if not data:
            sink.log(f"SKIP: no usable usage in {rollout_file.name}")
            return
        session_id = data["session_id"]
        mark_recorded(session_id)
        process_one(data, dry_run=args.dry_run)
        return

    # ── Sweep 模式(--since / --all / 无参数 = 全量) ──
    recorded = sink.recorded_sessions()
    files = list_rollout_files(args.since)
    sink.log(f"START scanning {len(files)} codex rollout files...")

    new_count = 0
    updated_count = 0
    changed_files: set[str] = set()

    for rf in files:
        try:
            data = parse_rollout(rf)
        except Exception as e:
            sink.error_log(f"parse failed for {rf.name}: {e}")
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

        if args.dry_run:
            print(f"[dry-run] {sink.format_row(data)}")
            continue

        changed_files.add(sink.upsert(data, data["_date"]))

    if new_count == 0 and updated_count == 0:
        sink.log("SKIP: no new or updated codex sessions")
        return

    sink.log(f"Recorded: {new_count} new, {updated_count} updated sessions across {len(changed_files)} files")
    if args.dry_run:
        print(f"[dry-run] {new_count} new, {updated_count} updated (not written)")
        return
    sink.git_sync(changed_files, f"track: codex token usage ({new_count} new, {updated_count} updated)")
    sink.log("DONE codex log-usage")


def process_one(data: dict, dry_run: bool = False) -> None:
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

    if dry_run:
        print(f"[dry-run] {sink.format_row(data)}")
        return

    rel_path = sink.upsert(data, date_str)
    sink.git_sync([rel_path], f"track: codex token usage ({1 if new else 0} new, {0 if new else 1} updated)")


if __name__ == "__main__":
    main()