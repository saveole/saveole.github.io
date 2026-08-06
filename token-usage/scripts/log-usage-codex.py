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
import platform
import socket
import subprocess
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

DATA_DIR = REPO_DIR / "token-usage"
ERROR_LOG = Path.home() / ".claude" / "hooks" / "tracker-errors.log"
LOG_FILE = Path.home() / ".claude" / "hooks" / "tracker.log"

# 节流:单文件模式(--rollout)下,同一 session 在 THROTTLE_MINUTES 分钟内只记录一次。
# Codex 的 notify 机制可能多次触发,节流避免频繁 commit + push;
# 兜底:下次全量/--since 扫描时,因 .data 里数据过期或缺失仍会补录。
THROTTLE_FILE = Path(os.environ.get("CODEX_THROTTLE_FILE", str(Path.home() / ".codex" / "tracker-throttle.json")))
THROTTLE_MINUTES = int(os.environ.get("CODEX_THROTTLE_MINUTES", "5"))

CST = timezone(timedelta(hours=8))

TSV_HEADER = "\t".join([
    "session_id", "timestamp", "project", "model",
    "duration_seconds", "message_count",
    "tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_creation",
    "git_branch", "tokens_reasoning", "source",
])

SOURCE = "codex"


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] [codex] {msg}\n")


def error_log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ERROR_LOG, "a") as f:
        f.write(f"[{ts}] [codex] {msg}\n")


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
    if not directory or not os.path.isdir(directory):
        return "unknown"
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
            cwd=directory,
        )
        branch = result.stdout.strip()
        return branch if branch else "unknown"
    except Exception:
        return "unknown"


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
        "source": SOURCE,
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


# ── Dedup against existing .data files ────────────────────────

def get_recorded_sessions() -> dict[str, tuple[str, dict]]:
    """Scan all .data files for existing codex records.
    Returns {session_id: (data_file_path, tokens_dict)}.
    """
    recorded: dict[str, tuple[str, dict]] = {}
    if not DATA_DIR.is_dir():
        return recorded
    for data_file in sorted(DATA_DIR.glob("*.data")):
        try:
            lines = data_file.read_text(encoding="utf-8").splitlines()
            if len(lines) < 2:
                continue
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
                    recorded[sid] = (str(data_file), tokens)
        except (OSError, ValueError):
            continue
    return recorded


def format_tsv_row(data: dict) -> str:
    return "\t".join([
        data["session_id"], data["timestamp"], data["project"], data["model"],
        str(data["duration_seconds"]), str(data["message_count"]),
        str(data["tokens_input"]), str(data["tokens_output"]),
        str(data["tokens_cache_read"]), str(data["tokens_cache_creation"]),
        data["git_branch"], str(data["tokens_reasoning"]), SOURCE,
    ])


def upsert_data_file(data_file: Path, session_id: str, tsv_row: str) -> None:
    """Replace existing session line or append new one (by session_id)."""
    lines: list[str] = []
    if data_file.is_file():
        lines = data_file.read_text(encoding="utf-8").splitlines(keepends=True)
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.startswith(session_id + "\t"):
            out.append(tsv_row + "\n")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        # 旧文件可能是 11 列 header(无 tokens_reasoning / source),
        # 顺手升级为 13 列,保证 build.js / aggregate.py 能识别 source
        if out and out[0].count("\t") == 10:
            out[0] = TSV_HEADER + "\n"
        if not out or not out[0].startswith("session_id\t"):
            out.insert(0, TSV_HEADER + "\n")
        out.append(tsv_row + "\n")
    data_file.write_text("".join(out), encoding="utf-8")


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

    if not REPO_DIR.is_dir():
        log(f"SKIP: REPO_DIR not found ({REPO_DIR})")
        return

    if args.rollout:
        rollout_file = Path(args.rollout)
        if not rollout_file.is_file():
            log(f"SKIP: rollout file not found ({rollout_file})")
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
            log(f"SKIP: session {session_id[:12]} throttled (< {THROTTLE_MINUTES}min)")
            return

        data = parse_rollout(rollout_file)
        if not data:
            log(f"SKIP: no usable usage in {rollout_file.name}")
            return
        session_id = data["session_id"]
        mark_recorded(session_id)
        process_one(data, dry_run=args.dry_run)
        return

    # ── Sweep 模式(--since / --all / 无参数 = 全量) ──
    recorded = get_recorded_sessions()
    files = list_rollout_files(args.since)
    log(f"START scanning {len(files)} codex rollout files...")

    new_count = 0
    updated_count = 0
    dirty_dates: set[str] = set()
    hostname = socket.gethostname()
    os_name = platform.system()

    for rf in files:
        try:
            data = parse_rollout(rf)
        except Exception as e:
            error_log(f"parse failed for {rf.name}: {e}")
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
            _, old = recorded[sid]
            if (old["input"] == t_input and
                    old["output"] == t_output and
                    old["cache_read"] == t_cache_read and
                    old["cache_creation"] == t_cache_creation and
                    old["reasoning"] == t_reasoning):
                continue
            updated_count += 1
            log(f"UPDATE session {sid[:12]} input={t_input} output={t_output}")
        else:
            new_count += 1
            log(f"NEW session {sid[:12]} input={t_input} output={t_output}")

        date_str = data["_date"]
        dirty_dates.add(date_str)

        if args.dry_run:
            print(f"[dry-run] {date_str}_{hostname}-{os_name}.data\t{format_tsv_row(data)}")
            continue

        data_file = DATA_DIR / f"{date_str}_{hostname}-{os_name}.data"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        upsert_data_file(data_file, sid, format_tsv_row(data))

    if new_count == 0 and updated_count == 0:
        log("SKIP: no new or updated codex sessions")
        return

    log(f"Recorded: {new_count} new, {updated_count} updated sessions across {len(dirty_dates)} dates")
    if args.dry_run:
        print(f"[dry-run] {new_count} new, {updated_count} updated (not written)")
        return
    git_sync(dirty_dates, new_count, updated_count, hostname, os_name)
    log("DONE codex log-usage")


def process_one(data: dict, dry_run: bool = False) -> None:
    """Hook mode: upsert a single session record + git sync."""
    sid = data["session_id"]
    date_str = data["_date"]
    hostname = socket.gethostname()
    os_name = platform.system()

    # 与 .data 已有记录比对:无变化则跳过(节流窗口过期后重查的场景)
    recorded = get_recorded_sessions()
    if sid in recorded:
        _, old = recorded[sid]
        if (old["input"] == data["tokens_input"] and
                old["output"] == data["tokens_output"] and
                old["cache_read"] == data["tokens_cache_read"] and
                old["cache_creation"] == data["tokens_cache_creation"] and
                old["reasoning"] == data["tokens_reasoning"]):
            log(f"SKIP: session {sid[:12]} unchanged in .data")
            return
        log(f"UPDATE session {sid[:12]} input={data['tokens_input']} output={data['tokens_output']}")
    else:
        log(f"NEW session {sid[:12]} input={data['tokens_input']} output={data['tokens_output']}")

    if dry_run:
        print(f"[dry-run] {date_str}_{hostname}-{os_name}.data\t{format_tsv_row(data)}")
        return

    data_file = DATA_DIR / f"{date_str}_{hostname}-{os_name}.data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    upsert_data_file(data_file, sid, format_tsv_row(data))

    git_sync({date_str}, 1 if sid not in recorded else 0,
             0 if sid not in recorded else 1, hostname, os_name)


def git_sync(dirty_dates: set[str], new_count: int, updated_count: int,
             hostname: str, os_name: str) -> None:
    """git add dirty .data files, commit, pull --rebase, push."""
    for date_str in dirty_dates:
        rel_path = f"token-usage/{date_str}_{hostname}-{os_name}.data"
        subprocess.run(["git", "add", rel_path], capture_output=True, cwd=str(REPO_DIR))

    t0 = time.monotonic()
    log("GIT: committing codex token usage...")
    if run_git("commit", "-m", f"track: codex token usage ({new_count} new, {updated_count} updated)"):
        log(f"GIT: commit OK ({int(time.monotonic() - t0)}s)")
    else:
        log(f"GIT: commit FAILED ({int(time.monotonic() - t0)}s)")

    t0 = time.monotonic()
    log("GIT: pulling --rebase origin main...")
    if run_git("pull", "--rebase", "origin", "main"):
        log(f"GIT: pull OK ({int(time.monotonic() - t0)}s)")
    else:
        log(f"GIT: pull FAILED ({int(time.monotonic() - t0)}s)")

    t0 = time.monotonic()
    log("GIT: pushing origin main...")
    if run_git("push", "origin", "main"):
        log(f"GIT: push OK ({int(time.monotonic() - t0)}s)")
    else:
        log(f"GIT: push FAILED ({int(time.monotonic() - t0)}s)")


if __name__ == "__main__":
    main()
