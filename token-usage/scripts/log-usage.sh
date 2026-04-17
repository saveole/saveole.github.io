#!/usr/bin/env bash
# ┌─────────────────────────────────────────────────────────────┐
# │  Claude Code Token Usage Tracker — Stop Hook               │
# │                                                             │
# │  将此脚本复制到 ~/.claude/hooks/log-usage.sh                │
# │  然后在 ~/.claude/settings.json 中注册 Stop hook            │
# │  详见 saveole.github.io/token-usage/README.md                                 │
# └─────────────────────────────────────────────────────────────┘
set -u

# ═══════════════════════════════════════════════════════════════
#  配置区（唯一需要修改的地方）
# ═══════════════════════════════════════════════════════════════

# saveole.github.io 仓库在本机的绝对路径
REPO_DIR="${TOKEN_USAGE_REPO_DIR:-$HOME/blog/saveole.github.io}"

# ═══════════════════════════════════════════════════════════════

DATA_DIR="${REPO_DIR}/token-usage"
LOCK_DIR="/tmp/claude-token-tracker.lockdir"
ERROR_LOG="${HOME}/.claude/hooks/tracker-errors.log"
LOG_FILE="${HOME}/.claude/hooks/tracker.log"

log() {
    local msg="[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*"
    echo "$msg" >> "$LOG_FILE"
}

# ── Guard: check dependencies ──
command -v jq &>/dev/null || { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] SKIP: jq not found" >> "$LOG_FILE"; exit 0; }
[[ -d "$REPO_DIR" ]] || { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] SKIP: REPO_DIR not found ($REPO_DIR)" >> "$LOG_FILE"; exit 0; }

# ── Read hook input from stdin ──
HOOK_INPUT=$(cat)
SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id // empty')
TRANSCRIPT_PATH=$(echo "$HOOK_INPUT" | jq -r '.transcript_path // empty')
CWD=$(echo "$HOOK_INPUT" | jq -r '.cwd // empty')

[[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]] || { log "SKIP: no valid transcript (session=$SESSION_ID)"; exit 0; }

log "START session=${SESSION_ID:0:8} cwd=$CWD"

# ── Concurrency lock (non-blocking, macOS/Linux compatible) ──
mkdir "$LOCK_DIR" 2>/dev/null || exit 0
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

# ── Parse transcript: deduplicate by message.id, sum tokens ──
TOKEN_JSON=$(jq -s '
    map(select(.type == "assistant")) |
    group_by(.message.id) |
    map(.[0]) |
    {
        input:          map(.message.usage.input_tokens // 0) | add,
        output:         map(.message.usage.output_tokens // 0) | add,
        cache_read:     map(.message.usage.cache_read_input_tokens // 0) | add,
        cache_creation: map(.message.usage.cache_creation_input_tokens // 0) | add
    }
' "$TRANSCRIPT_PATH" 2>/dev/null) || exit 0

INPUT_TOKENS=$(echo "$TOKEN_JSON" | jq -r '.input // 0')
OUTPUT_TOKENS=$(echo "$TOKEN_JSON" | jq -r '.output // 0')
[[ "$INPUT_TOKENS" != "0" || "$OUTPUT_TOKENS" != "0" ]] || { log "SKIP: zero tokens"; exit 0; }

log "TOKENS input=$INPUT_TOKENS output=$OUTPUT_TOKENS cache_read=$(echo "$TOKEN_JSON" | jq -r '.cache_read // 0') cache_creation=$(echo "$TOKEN_JSON" | jq -r '.cache_creation // 0')"

# ── Extract metadata ──
MODEL=$(jq -r 'select(.type == "assistant") | .message.model // "unknown"' "$TRANSCRIPT_PATH" 2>/dev/null \
    | sort | uniq -c | sort -rn | head -1 | awk '{print $2}' || true)
[[ -n "$MODEL" ]] || MODEL="unknown"

FIRST_TS=$(jq -r 'select(.type == "assistant") | .timestamp' "$TRANSCRIPT_PATH" 2>/dev/null | head -1 || true)
LAST_TS=$(jq -r 'select(.type == "assistant") | .timestamp' "$TRANSCRIPT_PATH" 2>/dev/null | tail -1 || true)

DURATION=0
if [[ -n "$FIRST_TS" && -n "$LAST_TS" ]]; then
    FIRST_EPOCH=$(date -d "$FIRST_TS" +%s 2>/dev/null) || FIRST_EPOCH=0
    LAST_EPOCH=$(date -d "$LAST_TS" +%s 2>/dev/null) || LAST_EPOCH=0
    DURATION=$((LAST_EPOCH - FIRST_EPOCH))
fi

MSG_COUNT=$(jq -s 'map(select(.type == "assistant")) | group_by(.message.id) | length' "$TRANSCRIPT_PATH" 2>/dev/null) || MSG_COUNT=0

PROJECT="unknown"
if [[ -n "$CWD" ]]; then
    PROJECT=$(basename "$CWD")
fi

GIT_BRANCH=$(jq -r 'select(.type == "assistant") | .gitBranch // "unknown"' "$TRANSCRIPT_PATH" 2>/dev/null | head -1 || true)
[[ -n "$GIT_BRANCH" ]] || GIT_BRANCH="unknown"

NOW=$(date +"%Y-%m-%dT%H:%M:%S+08:00")
DATE=$(date +"%Y-%m-%d")

# ── Extract token fields ──
INPUT_TOKENS=$(echo "$TOKEN_JSON" | jq -r '.input // 0')
OUTPUT_TOKENS=$(echo "$TOKEN_JSON" | jq -r '.output // 0')
CACHE_READ=$(echo "$TOKEN_JSON" | jq -r '.cache_read // 0')
CACHE_CREATION=$(echo "$TOKEN_JSON" | jq -r '.cache_creation // 0')

# ── Build TSV record (11 fields, matching SCHEMA.md) ──
TSV_RECORD=$(printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' \
    "$SESSION_ID" "$NOW" "$PROJECT" "$MODEL" \
    "$DURATION" "$MSG_COUNT" \
    "$INPUT_TOKENS" "$OUTPUT_TOKENS" "$CACHE_READ" "$CACHE_CREATION" \
    "$GIT_BRANCH")

# ── Deduplicate by session_id ──
DATA_FILE="${DATA_DIR}/${DATE}.data"
if [[ -f "$DATA_FILE" ]]; then
    if grep -q "$SESSION_ID" "$DATA_FILE" 2>/dev/null; then
        log "SKIP: session ${SESSION_ID:0:8} already recorded"
        exit 0
    fi
fi

# ── Append and sync ──
mkdir -p "$DATA_DIR"
TSV_HEADER="session_id"$'\t'"timestamp"$'\t'"project"$'\t'"model"$'\t'"duration_seconds"$'\t'"message_count"$'\t'"tokens_input"$'\t'"tokens_output"$'\t'"tokens_cache_read"$'\t'"tokens_cache_creation"$'\t'"git_branch"
if [[ ! -f "$DATA_FILE" ]]; then
    printf '%s\n' "$TSV_HEADER" > "$DATA_FILE"
fi
printf '%s\n' "$TSV_RECORD" >> "$DATA_FILE"

cd "$REPO_DIR"
git add "token-usage/${DATE}.data" 2>/dev/null || true
if ! git diff --cached --quiet 2>/dev/null; then
    log "GIT: pulling origin main..."
    if git pull --rebase origin main 2>>"$ERROR_LOG"; then
        log "GIT: pull OK"
    else
        log "GIT: pull FAILED (see $ERROR_LOG)"
    fi

    log "GIT: committing session ${SESSION_ID:0:8}..."
    if git commit -m "track: token usage ${DATE} session ${SESSION_ID:0:8}" 2>>"$ERROR_LOG"; then
        log "GIT: commit OK"
    else
        log "GIT: commit FAILED (see $ERROR_LOG)"
    fi

    log "GIT: pushing origin main..."
    if git push origin main 2>>"$ERROR_LOG"; then
        log "GIT: push OK"
    else
        log "GIT: push FAILED (see $ERROR_LOG)"
    fi
else
    log "GIT: no changes to commit"
fi

log "DONE session=${SESSION_ID:0:8}"
exit 0
