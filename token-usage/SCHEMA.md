# TSV Data Format Specification

## Overview

Token usage data is stored as TSV (Tab-Separated Values) files with a single header line followed by one data row per session. This format replaces the previous JSONL storage to reduce file size by ~65% while preserving all essential fields.

## Column Schema

| # | Column Name             | Type    | Description                                    | Example Value                        |
|---|-------------------------|---------|------------------------------------------------|--------------------------------------|
| 1 | session_id              | string  | Unique session identifier (UUID)               | 426a4a26-94ba-401f-be63-96aa17803446 |
| 2 | timestamp               | string  | ISO 8601 CST timestamp (UTC+8)                 | 2026-04-15T19:48:03+08:00            |
| 3 | project                 | string  | Project name (basename of working directory)    | blog                                 |
| 4 | model                   | string  | Model name / ID                                | deepseek-v4-pro                      |
| 5 | duration_seconds        | integer | Session duration in seconds                    | 54                                   |
| 6 | message_count           | integer | Number of messages                             | 11                                   |
| 7 | tokens_input            | integer | Total input tokens consumed                    | 25195                                |
| 8 | tokens_output           | integer | Total output tokens generated                  | 1374                                 |
| 9 | tokens_cache_read       | integer | Tokens served from prompt cache (read)          | 87680                                |
| 10| tokens_cache_creation   | integer | Tokens written to prompt cache (creation)       | 0                                    |
| 11| git_branch              | string  | Git branch name at session time                | main                                 |
| 12| tokens_reasoning        | integer | Tokens consumed for reasoning (thinking)        | 175                                  |
| 13| source                  | string  | Data source identifier (claude / opencode)     | opencode                             |

**Total: 13 columns, tab-delimited.**

## Removed Fields

The following field from the JSONL format is intentionally excluded (removed):

- **project_path** — removed (excluded from TSV); `project` (the directory basename) is sufficient for usage tracking. The full filesystem path is not needed for analytics.

## Header Row

Every `.data` file **must** begin with a header row containing the column names listed above, in the exact order shown, separated by tabs. The header serves as the self-describing contract for the file.

```
session_id\ttimestamp\tproject\tmodel\tduration_seconds\tmessage_count\ttokens_input\ttokens_output\ttokens_cache_read\ttokens_cache_creation\tgit_branch\ttokens_reasoning\tsource
```

- The header is always the **first line** of the file.
- Subsequent lines are data rows with values in the same column order.
- All 13 tab-separated fields must be present on every data row (empty strings for missing values are not expected but tolerated).

## File Naming Convention

- **Filename format**: `YYYY-MM-DD_{hostname}-{os}.data` (e.g., `2026-04-15_myhost-Linux.data`)
  - `hostname`: System hostname (from `hostname` command or `platform.node()`)
  - `os`: Operating system name (from `uname -s` or `platform.system()`, e.g., "Linux", "Darwin")
- One file per calendar day (UTC) **per device**, containing all sessions that started on that day from that device.
- **Encoding**: UTF-8, no BOM.
- **Line endings**: Unix-style (`\n`), no trailing newline at end of file.

## Data Source Mapping

### Claude Code (JSONL to TSV)

数据来源为 Claude Code 本地会话文件（`~/.claude/projects/<project>/<session>.jsonl`），每行一个 JSON 对象。脚本仅处理 `type == "assistant"` 的行，按 `message.id` 去重后聚合。

| JSONL Path                              | TSV Column             | Transformation                         |
|-----------------------------------------|------------------------|----------------------------------------|
| `sessionId`                             | session_id             | Direct copy                            |
| *(record time)*                         | timestamp              | 当前时刻 (CST +08:00)                   |
| *(from path: projects/\<name\>/)*       | project                | 从文件路径提取 project 目录名            |
| `message.model`                         | model                  | 取频率最高的 model；`speed=="fast"` 追加 `-fast` |
| *(computed from timestamps)*            | duration_seconds       | 首末条 assistant timestamp 之差         |
| *(count unique `message.id`)*           | message_count          | 去重计数                               |
| `message.usage.input_tokens`            | tokens_input           | Sum across deduplicated messages       |
| `message.usage.output_tokens`           | tokens_output          | Sum across deduplicated messages       |
| `message.usage.cache_read_input_tokens` | tokens_cache_read      | Sum across deduplicated messages       |
| `message.usage.cache_creation_input_tokens` | tokens_cache_creation | Sum across deduplicated messages    |
| `gitBranch`                             | git_branch             | 取第一条 assistant 消息的值             |
| *(N/A — Claude Code)*                   | tokens_reasoning       | 固定为 0                               |
| `"claude"`                              | source                 | 固定为 `claude`                        |

### OpenCode (SQLite to TSV)

数据来源为 OpenCode 本地 SQLite 数据库（`~/.local/share/opencode/opencode.db`），`session` 表已预聚合。

| SQLite Column / Source     | TSV Column             | Transformation                         |
|----------------------------|------------------------|----------------------------------------|
| `session.id`               | session_id             | Direct copy                            |
| `session.time_created`     | timestamp              | epoch ms → ISO CST                     |
| `project.name` / directory | project                | DB project name，fallback 到目录 basename |
| `session.model` (JSON)     | model                  | 提取 JSON `.id` 字段                   |
| `time_updated - time_created` | duration_seconds    | 毫秒差 → 秒                            |
| `COUNT(message)`           | message_count          | SQL COUNT query                        |
| `session.tokens_input`     | tokens_input           | Direct copy                            |
| `session.tokens_output`    | tokens_output          | Direct copy                            |
| `session.tokens_cache_read` | tokens_cache_read     | Direct copy                            |
| `session.tokens_cache_write` | tokens_cache_creation | Direct copy                            |
| `git branch --show-current` | git_branch            | 从 session.directory 执行 git 命令      |
| `session.tokens_reasoning` | tokens_reasoning       | Direct copy                            |
| `"opencode"`               | source                 | 固定为 `opencode`                      |

## Example

**JSONL assistant entry (input)** — `~/.claude/projects/-home-ant-blog/74fae944-...jsonl` 中的一行：
```json
{
  "type": "assistant",
  "sessionId": "74fae944-a291-4109-b646-687343e146f0",
  "timestamp": "2026-04-24T02:14:26.890Z",
  "gitBranch": "main",
  "message": {
    "id": "msg_20260424101421ba7ac6ac5c20419a",
    "model": "glm-5.1",
    "usage": {
      "input_tokens": 8979,
      "output_tokens": 53,
      "cache_read_input_tokens": 17984,
      "cache_creation_input_tokens": 0,
      "speed": "standard"
    }
  }
}
```

**TSV data row (output)** — 聚合整个 session 后写入 `.data` 文件：
```
74fae944-a291-4109-b646-687343e146f0\t2026-04-24T10:55:17+08:00\t-home-ant-blog\tglm-5.1\t2324\t19\t27678\t9552\t679296\t0\tmain\t0\tclaude
```

**OpenCode TSV example:**
```
ses_12b7a7441ffe28fJLuv9J35Vai\t2026-06-17T15:30:00+08:00\tsaveole.github.io\tdeepseek-v4-pro\t540\t18\t34412\t1746\t241280\t0\tmain\t220\topencode
```
