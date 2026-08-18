#!/usr/bin/env python3
"""Deep shared sink for the token-usage trackers.

Every agent tracker (claude, opencode, agy, zcode, pi, codex) extracts token
usage from a different source — a JSONL transcript, a SQLite DB, a rollout
file — then does the *same* thing with the result: build a 13-column TSV row,
upsert it into a daily YYYY-MM-DD_{hostname}-{os}.data file keyed by
session_id, and sync the repo to git. That common tail is the session log.

This module is the session-log sink. The per-agent scripts shrink to thin
adapters: extract from their source, build a record dict, call ``upsert`` and
``git_sync`` here. The TSV schema, the filename rule, dedup, the legacy
11->13 column migration, and the git add/commit/pull/push dance live in one
place and are testable through this module's interface.
"""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))

TSV_HEADER = "\t".join([
    "session_id", "timestamp", "project", "model",
    "duration_seconds", "message_count",
    "tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_creation",
    "git_branch", "tokens_reasoning", "source",
])

TOKEN_KEYS = ("input", "output", "cache_read", "cache_creation", "reasoning")

_ALL_SOURCES = object()  # sentinel: scan every source, not just this sink's


def _default_repo_dir() -> Path:
    return Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))


class TrackerSink:
    """The session log: TSV read/write + git sync, shared by all trackers.

    Construct with the agent source name; the paths default to the standard
    repo/hook locations but can be injected for tests.
    """

    def __init__(
        self,
        source: str,
        repo_dir: Path | None = None,
        data_dir: Path | None = None,
        log_file: Path | None = None,
        error_log_file: Path | None = None,
        log_prefix: str | None = None,
        branch_fallback: str = "unknown",
    ) -> None:
        self.source = source
        self.repo_dir = repo_dir or _default_repo_dir()
        self.data_dir = data_dir or self.repo_dir / "token-usage"
        self.log_file = log_file or Path.home() / ".claude" / "hooks" / "tracker.log"
        self.error_log_file = error_log_file or Path.home() / ".claude" / "hooks" / "tracker-errors.log"
        self.log_prefix = log_prefix  # e.g. "[zcode]" — mirrors old per-adapter log lines
        self.branch_fallback = branch_fallback  # "main" or "unknown"

    # ── logging ────────────────────────────────────────────────────────────

    def _format(self, msg: str) -> str:
        return f"{self.log_prefix} {msg}" if self.log_prefix else msg

    def log(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a") as f:
                f.write(f"[{ts}] {self._format(msg)}\n")
        except Exception:
            pass

    def error_log(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            self.error_log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.error_log_file, "a") as f:
                f.write(f"[{ts}] {self._format(msg)}\n")
        except Exception:
            pass

    # ── git ────────────────────────────────────────────────────────────────

    def run_git(self, *args: str, timeout: int = 120) -> bool:
        """Run a git command in the repo; log stderr on failure. True on success."""
        try:
            result = subprocess.run(
                ["git", *args],
                capture_output=True, text=True, timeout=timeout,
                cwd=str(self.repo_dir),
            )
            if result.returncode != 0:
                for line in result.stderr.strip().splitlines():
                    if line:
                        self.error_log(line)
            return result.returncode == 0
        except Exception as e:
            self.error_log(str(e))
            return False

    def git_branch(self, directory: str) -> str:
        """Current branch in a directory (the session's project), or the fallback."""
        if not directory:
            return self.branch_fallback
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=10,
                cwd=directory,
            )
            branch = result.stdout.strip()
            return branch if branch else self.branch_fallback
        except Exception:
            return self.branch_fallback

    # ── session log read ───────────────────────────────────────────────────

    def recorded_sessions(self, source: str | object | None = None) -> dict[str, dict[str, int]]:
        """Scan all .data files for sessions.

        Returns {session_id: {input, output, cache_read, cache_creation,
        reasoning}} — the token snapshot used for dedup. By default only this
        sink's source's sessions are returned; pass source="<other>" to filter
        by another source, or source=ALL_SOURCES for every source.
        """
        if source is None:
            source = self.source
        recorded: dict[str, dict[str, int]] = {}
        if not self.data_dir.is_dir():
            return recorded
        for data_file in sorted(self.data_dir.glob("*.data")):
            try:
                lines = data_file.read_text(encoding="utf-8").splitlines()
            except (OSError, ValueError):
                continue
            if len(lines) < 2:
                continue
            for line in lines[1:]:
                if not line.strip():
                    continue
                cols = line.split("\t")
                sid = cols[0] if len(cols) > 0 else ""
                src = cols[12] if len(cols) > 12 else ""
                if sid and (source is _ALL_SOURCES or src == source):
                    recorded[sid] = {
                        "input": int(cols[6]) if len(cols) > 6 else 0,
                        "output": int(cols[7]) if len(cols) > 7 else 0,
                        "cache_read": int(cols[8]) if len(cols) > 8 else 0,
                        "cache_creation": int(cols[9]) if len(cols) > 9 else 0,
                        "reasoning": int(cols[11]) if len(cols) > 11 else 0,
                    }
        return recorded

    # ── session log write ──────────────────────────────────────────────────

    def format_row(self, record: dict) -> str:
        """Build the 13-column TSV row for a record, tagging it with source."""
        return "\t".join([
            record["session_id"], record["timestamp"], record["project"], record["model"],
            str(record["duration_seconds"]), str(record["message_count"]),
            str(record["tokens_input"]), str(record["tokens_output"]),
            str(record["tokens_cache_read"]), str(record["tokens_cache_creation"]),
            record["git_branch"], str(record["tokens_reasoning"]), self.source,
        ])

    def upsert(self, record: dict, date: str) -> str:
        """Write or replace a session row keyed by session_id.

        Appends to the daily file for ``date`` (YYYY-MM-DD), or replaces the
        matching session_id line. Upgrades a legacy 11-column header to 13.
        Returns the repo-relative path of the touched file for git add.
        """
        data_file = self.data_dir / f"{date}_{self._hostname()}-{self._os()}.data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tsv_row = self.format_row(record)

        lines: list[str] = []
        if data_file.is_file():
            lines = data_file.read_text(encoding="utf-8").splitlines(keepends=True)
            # Upgrade old 11-column header to 13 columns if needed
            if lines and lines[0].count("\t") == 10:
                lines[0] = TSV_HEADER + "\n"
                for idx in range(1, len(lines)):
                    if lines[idx].strip():
                        cols = lines[idx].rstrip("\n").split("\t")
                        while len(cols) < 13:
                            cols.append("0" if len(cols) < 12 else "claude")
                        lines[idx] = "\t".join(cols) + "\n"

        replaced = False
        out: list[str] = []
        for line in lines:
            if line.startswith(record["session_id"] + "\t"):
                out.append(tsv_row + "\n")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            if not out or not out[0].startswith("session_id\t"):
                out.insert(0, TSV_HEADER + "\n")
            out.append(tsv_row + "\n")
        data_file.write_text("".join(out), encoding="utf-8")
        return str(data_file.relative_to(self.repo_dir))

    # ── git sync ───────────────────────────────────────────────────────────

    def git_sync(self, rel_paths: list[str] | set[str], message: str) -> None:
        """Add the touched files, commit, pull --rebase, push."""
        for rel in rel_paths:
            subprocess.run(["git", "add", str(rel)], capture_output=True, cwd=str(self.repo_dir))

        t0 = time.monotonic()
        self.log(f"GIT: committing {self.source} token usage...")
        if self.run_git("commit", "-m", message):
            self.log(f"GIT: commit OK ({int(time.monotonic() - t0)}s)")
        else:
            self.log(f"GIT: commit FAILED ({int(time.monotonic() - t0)}s)")

        t0 = time.monotonic()
        self.log("GIT: pulling --rebase origin main...")
        if self.run_git("pull", "--rebase", "origin", "main"):
            self.log(f"GIT: pull OK ({int(time.monotonic() - t0)}s)")
        else:
            self.log(f"GIT: pull FAILED ({int(time.monotonic() - t0)}s)")

        t0 = time.monotonic()
        self.log("GIT: pushing origin main...")
        if self.run_git("push", "origin", "main"):
            self.log(f"GIT: push OK ({int(time.monotonic() - t0)}s)")
        else:
            self.log(f"GIT: push FAILED ({int(time.monotonic() - t0)}s)")

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _hostname() -> str:
        return socket.gethostname()

    @staticmethod
    def _os() -> str:
        return platform.system()