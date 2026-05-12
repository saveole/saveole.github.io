#!/usr/bin/env python3
# ┌─────────────────────────────────────────────────────────────┐
# │  Claude Code Token Usage Tracker — SessionEnd Hook         │
# │                                                             │
# │  参考 ccusage (github.com/ryoppippi/ccusage) 的数据读取方式  │
# │  直接从 ~/.claude/projects/ 读取 JSONL，不依赖 transcript   │
# │  在 ~/.claude/settings.json 中注册为 SessionEnd hook        │
# │  详见 saveole.github.io/token-usage/README.md               │
# └─────────────────────────────────────────────────────────────┘
from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  配置区（唯一需要修改的地方）
# ═══════════════════════════════════════════════════════════════
REPO_DIR = Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))

# ═══════════════════════════════════════════════════════════════
#  Claude Code 数据目录（ccusage 兼容）
# ═══════════════════════════════════════════════════════════════
_config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
CLAUDE_DATA_DIRS: list[Path] = []
_env_dirs = os.environ.get("CLAUDE_CONFIG_DIR", "")
if _env_dirs:
    CLAUDE_DATA_DIRS = [Path(d) for d in _env_dirs.split(",") if d.strip()]
else:
    # v1.0.30+: ~/.config/claude/projects/ ; legacy: ~/.claude/projects/
    CLAUDE_DATA_DIRS = [
        _config_home / "claude",
        Path.home() / ".claude",
    ]

DATA_DIR = REPO_DIR / "token-usage"
LOCK_FILE = Path("/tmp/claude-token-tracker.lock")
ERROR_LOG = Path.home() / ".claude" / "hooks" / "tracker-errors.log"
LOG_FILE = Path.home() / ".claude" / "hooks" / "tracker.log"

CST = timezone(timedelta(hours=8))

TSV_HEADER = "\t".join([
    "session_id", "timestamp", "project", "model",
    "duration_seconds", "message_count",
    "tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_creation",
    "git_branch",
])


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


# ── ccusage-style session discovery ───────────────────────────

def find_session_jsonl(session_id: str) -> Path | None:
    """在 Claude 数据目录中查找 session JSONL 文件（ccusage 方式）"""
    for base in CLAUDE_DATA_DIRS:
        projects_dir = base / "projects"
        if not projects_dir.is_dir():
            continue
        # 搜索 **/{session_id}.jsonl
        matches = list(projects_dir.glob(f"**/{session_id}.jsonl"))
        if matches:
            return matches[0]
    return None


def extract_project_from_path(jsonl_path: Path) -> str:
    """从 JSONL 路径中提取项目名（ccusage extractProjectFromPath）"""
    parts = jsonl_path.parts
    for i, p in enumerate(parts):
        if p == "projects" and i + 1 < len(parts):
            return parts[i + 1]
    return "unknown"


def parse_session_jsonl(path: Path) -> dict | None:
    """解析 session JSONL（ccusage data-loader 方式）
    按 message.id 去重，汇总 token 使用量"""
    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_creation = 0
    seen_ids: set[str] = set()
    model_counts: dict[str, int] = {}
    timestamps: list[str] = []
    git_branch: str | None = None

    with open(path) as f:
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
            if not msg_id or msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)

            usage = msg.get("usage", {})
            input_tokens += usage.get("input_tokens", 0) or 0
            output_tokens += usage.get("output_tokens", 0) or 0
            cache_read += usage.get("cache_read_input_tokens", 0) or 0
            cache_creation += usage.get("cache_creation_input_tokens", 0) or 0

            # ccusage: speed=="fast" 时 model 追加 -fast 后缀
            model = msg.get("model", "")
            if model:
                speed = usage.get("speed", "")
                if speed == "fast":
                    model = f"{model}-fast"
                model_counts[model] = model_counts.get(model, 0) + 1

            ts = entry.get("timestamp")
            if ts:
                timestamps.append(ts)

            if git_branch is None:
                git_branch = entry.get("gitBranch")

    if not seen_ids:
        return None

    model = max(model_counts, key=model_counts.get) if model_counts else "unknown"

    duration = 0
    if len(timestamps) >= 2:
        try:
            first = datetime.fromisoformat(timestamps[0])
            last = datetime.fromisoformat(timestamps[-1])
            duration = int((last - first).total_seconds())
        except (ValueError, TypeError):
            pass

    return {
        "input": input_tokens,
        "output": output_tokens,
        "cache_read": cache_read,
        "cache_creation": cache_creation,
        "model": model,
        "duration": duration,
        "message_count": len(seen_ids),
        "git_branch": git_branch or "unknown",
    }


# ── Lock / main ───────────────────────────────────────────────

def acquire_lock() -> bool:
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_WRONLY | os.O_EXCL)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def main() -> None:
    if not REPO_DIR.is_dir():
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] SKIP: REPO_DIR not found ({REPO_DIR})\n")
        return

    # ── Read hook input from stdin ──
    hook_input = sys.stdin.read().strip()
    if not hook_input:
        return

    try:
        hook = json.loads(hook_input)
    except json.JSONDecodeError:
        return

    session_id = hook.get("session_id", "")
    cwd = hook.get("cwd", "")

    log(f"START session={session_id[:8]} cwd={cwd}")

    # ── Find JSONL via ccusage-style discovery ──
    jsonl_path = find_session_jsonl(session_id)

    # Fallback: hook 提供的 transcript_path
    if jsonl_path is None:
        transcript_path = hook.get("transcript_path", "")
        if transcript_path and Path(transcript_path).is_file():
            jsonl_path = Path(transcript_path)
            log(f"FALLBACK: using transcript_path={transcript_path}")

    if jsonl_path is None:
        log(f"SKIP: no JSONL found for session={session_id[:8]}")
        return

    log(f"JSONL: {jsonl_path}")

    if not acquire_lock():
        return

    try:
        _run(session_id, jsonl_path, cwd)
    finally:
        release_lock()


def _run(session_id: str, jsonl_path: Path, cwd: str) -> None:
    data = parse_session_jsonl(jsonl_path)
    if data is None:
        log("SKIP: no assistant messages")
        return

    if data["input"] == 0 and data["output"] == 0:
        log("SKIP: zero tokens")
        return

    log(
        f"TOKENS input={data['input']} output={data['output']} "
        f"cache_read={data['cache_read']} cache_creation={data['cache_creation']}"
    )

    # 项目名优先从路径提取（ccusage 方式），回退到 cwd basename
    project = extract_project_from_path(jsonl_path)
    if project == "unknown" and cwd:
        project = os.path.basename(cwd)

    now = datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    date = datetime.now(CST).strftime("%Y-%m-%d")
    hostname = socket.gethostname()
    os_name = platform.system()

    record = "\t".join([
        session_id, now, project, data["model"],
        str(data["duration"]), str(data["message_count"]),
        str(data["input"]), str(data["output"]),
        str(data["cache_read"]), str(data["cache_creation"]),
        data["git_branch"],
    ])

    # ── Deduplicate / update by session_id ──
    data_file = DATA_DIR / f"{date}_{hostname}-{os_name}.data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if data_file.is_file():
        lines = data_file.read_text().splitlines(keepends=True)
        replaced = False
        new_lines: list[str] = []
        for line in lines:
            if line.startswith(session_id + "\t"):
                # Replace with updated record
                new_lines.append(record + "\n")
                replaced = True
            else:
                new_lines.append(line)
        if replaced:
            data_file.write_text("".join(new_lines))
            log(f"UPDATE: session {session_id[:8]} token counts updated")
        else:
            with open(data_file, "a") as f:
                f.write(record + "\n")
    else:
        with open(data_file, "w") as f:
            f.write(TSV_HEADER + "\n")
            f.write(record + "\n")

    # ── Git sync ──
    subprocess.run(
        ["git", "add", f"token-usage/{date}_{hostname}-{os_name}.data"],
        capture_output=True, cwd=str(REPO_DIR),
    )

    t0 = time.monotonic()
    log(f"GIT: committing session {session_id[:8]}...")
    if run_git("commit", "-m", f"track: token usage {date} session {session_id[:8]}"):
        log(f"GIT: commit OK ({int(time.monotonic() - t0)}s)")
    else:
        log(f"GIT: commit FAILED ({int(time.monotonic() - t0)}s, see {ERROR_LOG})")

    t0 = time.monotonic()
    log("GIT: pulling --rebase origin main...")
    if run_git("pull", "--rebase", "origin", "main"):
        log(f"GIT: pull OK ({int(time.monotonic() - t0)}s)")
    else:
        log(f"GIT: pull FAILED ({int(time.monotonic() - t0)}s, see {ERROR_LOG})")

    t0 = time.monotonic()
    log("GIT: pushing origin main...")
    if run_git("push", "origin", "main"):
        log(f"GIT: push OK ({int(time.monotonic() - t0)}s)")
    else:
        log(f"GIT: push FAILED ({int(time.monotonic() - t0)}s, see {ERROR_LOG})")

    # ── Background incremental scan + git sync ──
    incremental = REPO_DIR / "token-usage" / "scripts" / "incremental.py"
    if incremental.is_file():
        sync_script = (
            f'{sys.executable} "{incremental}" '
            f'&& cd "{REPO_DIR}" '
            f'&& git add token-usage/ '
            f'&& git diff --cached --quiet || git commit -m "track: token usage incremental update" '
            f'&& git pull --rebase origin main '
            f'&& git push origin main'
        )
        subprocess.Popen(
            ["bash", "-c", sync_script],
            stdout=open(LOG_FILE, "a"),
            stderr=subprocess.STDOUT,
        )

    log(f"DONE session={session_id[:8]}")


if __name__ == "__main__":
    main()
