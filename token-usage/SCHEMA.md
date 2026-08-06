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
| 13| source                  | string  | Data source identifier (claude / opencode / hermes / agy / zcode / pi / codex) | zcode                                  |

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

### Antigravity CLI (agy)

数据来源为 Antigravity CLI 本地会话记录（`~/.gemini/antigravity-cli/brain/<cid>/.system_generated/logs/transcript_full.jsonl`），以及 `history.jsonl` / `conversations/<cid>.db` 数据库。

| Source / Field                           | TSV Column             | Transformation                         |
|------------------------------------------|------------------------|----------------------------------------|
| `conversationId` (`cid`)                | session_id             | Direct copy                            |
| `created_at` (first entry)               | timestamp              | 首条记录 timestamp (ISO CST)            |
| `history.jsonl` -> `workspace`          | project                | workspace 目录 basename                 |
| `conversations/<cid>.db` -> metadata     | model                  | 正则匹配模型名 (如 gemini-3.6-flash)    |
| *(computed from timestamps)*            | duration_seconds       | 首末条 created_at 之差                 |
| *(count messages)*                       | message_count          | USER_INPUT + PLANNER_RESPONSE 消息数   |
| USER_INPUT + tool result chars           | tokens_input           | 字符数 * 0.35 估算                      |
| PLANNER_RESPONSE + tool call json chars  | tokens_output          | 字符数 * 0.35 估算                      |
| *(N/A — agy)*                            | tokens_cache_read      | 固定为 0                               |
| *(N/A — agy)*                            | tokens_cache_creation | 固定为 0                               |
| `git branch --show-current`              | git_branch             | 从 workspace 目录执行 git 命令          |
| PLANNER_RESPONSE `thinking` chars        | tokens_reasoning       | thinking 字符数 * 0.35 估算            |
| `"agy"`                                  | source                 | 固定为 `agy`                           |

### ZCode (SQLite to TSV)

数据来源为 ZCode 本地 SQLite 数据库（`~/.zcode/cli/db/db.sqlite`）。`model_usage` 表按每次模型请求记录 token，`session` 表存储会话元数据。

**子代理归并**：ZCode 把 subagent 作为独立 session 存储（`task_type='subagent_child'`，`parent_id` 链回主会话）。脚本用递归 CTE 沿 `parent_id` 链收集主会话及其所有子会话，token 累加到父会话——每个 interactive session 只产生一行 TSV 记录。

| SQLite Source / Field                     | TSV Column             | Transformation                         |
|------------------------------------------|------------------------|----------------------------------------|
| `session.id`                             | session_id             | 直接用（含 `sess_` 前缀）              |
| `session.time_created`                   | timestamp              | epoch ms → ISO CST (+08:00)            |
| `session.directory`                      | project                | 目录 basename                           |
| `model_usage.model_id`（树内最高频）       | model                  | 递归 CTE 内 GROUP BY model_id 取 COUNT DESC |
| `MAX(completed_at) - MIN(started_at)`    | duration_seconds       | ms → 秒                                |
| `turn_usage` 树内 COUNT(*)               | message_count          | 对话轮次数                             |
| `SUM(model_usage.input_tokens)`          | tokens_input           | 递归 CTE 内求和，含 subagent           |
| `SUM(model_usage.output_tokens)`         | tokens_output          | 递归 CTE 内求和，含 subagent           |
| `SUM(model_usage.cache_read_input_tokens)` | tokens_cache_read    | 递归 CTE 内求和，含 subagent           |
| `SUM(model_usage.cache_creation_input_tokens)` | tokens_cache_creation | 递归 CTE 内求和（当前 GLM 模型为 0） |
| `git branch --show-current`（session.directory） | git_branch      | 子进程执行                             |
| `SUM(model_usage.reasoning_tokens)`      | tokens_reasoning       | 递归 CTE 内求和（当前 GLM 模型为 0）   |
| `"zcode"`                                | source                 | 固定为 `zcode`                         |

**过滤条件**：`model_usage.status = 'completed'`（cancelled / error 请求 token 为 0，过滤无数据损失）。

**递归 CTE 示例**（归并 subagent）：
```sql
WITH RECURSIVE session_tree(id) AS (
    SELECT ?                       -- 根 interactive session_id
    UNION ALL
    SELECT s.id FROM session s JOIN session_tree t ON s.parent_id = t.id
)
SELECT ... FROM model_usage mu
WHERE mu.session_id IN (SELECT id FROM session_tree) AND mu.status = 'completed';
```

### pi (JSONL to TSV)

数据来源为 pi coding agent 本地会话文件（`~/.pi/agent/sessions/**/*.jsonl`）。pi 的每条 assistant 消息直接携带 `usage` 字段（无需解析嵌套结构或估算），统计范围与 pi footer 显示的总量一致：assistant 消息 + toolResult 内嵌 usage（工具内部 LLM 工作）+ compaction / branch_summary 的 usage（摘要生成）。

| JSONL Path                              | TSV Column             | Transformation                         |
|-----------------------------------------|------------------------|----------------------------------------|
| header `id`                             | session_id             | Direct copy（兜底取文件名 uuid）       |
| header `timestamp`                      | timestamp              | ISO → CST +08:00                      |
| header `cwd`                            | project                | 目录 basename                          |
| `message.model`(频率最高)               | model                  | 取出现次数最多的 model id              |
| *(首末条 entry timestamp 之差)*          | duration_seconds       | max - min（秒）                        |
| *(assistant 消息计数)*                   | message_count          | 带 usage 的 assistant 消息数          |
| `usage.input`                           | tokens_input           | Sum across entries                    |
| `usage.output`                          | tokens_output          | Sum across entries                    |
| `usage.cacheRead`                       | tokens_cache_read      | Sum across entries                    |
| `usage.cacheWrite`                      | tokens_cache_creation  | Sum across entries                    |
| `git branch --show-current`(header cwd) | git_branch             | 子进程执行                             |
| `usage.reasoning`                       | tokens_reasoning       | Sum across entries                    |
| `"pi"`                                  | source                 | 固定为 `pi`                            |

**统计范围**：assistant（每次 LLM 调用）+ toolResult 内嵌 usage + compaction / branch_summary usage。

### Codex (rollout JSONL to TSV)

数据来源为 Codex CLI 本地会话文件（`~/.codex/sessions/**/rollout-*.jsonl`）。每个 rollout 是一行一个 JSON 事件：`session_meta` 提供会话元数据，`event_msg` 的 `token_count` 事件携带**累计** token 用量（`info.total_token_usage`），取最后一次即为会话最终用量。

| Rollout JSONL Path                              | TSV Column             | Transformation                         |
|-------------------------------------------------|------------------------|----------------------------------------|
| `session_meta.payload.session_id` / `id`        | session_id             | Direct copy（兜底取文件名末尾 UUID）   |
| `session_meta.payload.timestamp`                | timestamp              | ISO → CST +08:00                       |
| `session_meta.payload.cwd`                      | project                | 目录 basename                           |
| `turn_context` / `response_item` 的 `payload.model` | model              | 取出现次数最多的 model id               |
| *(首末事件 timestamp 之差)*                      | duration_seconds       | max - min（秒）                         |
| *(assistant response_item 计数)*                | message_count          | role == "assistant" 的消息数            |
| `total_token_usage.input_tokens - cached_input_tokens` | tokens_input    | 新输入（不含缓存）                      |
| `total_token_usage.output_tokens`               | tokens_output          | Direct copy                             |
| `total_token_usage.cached_input_tokens`         | tokens_cache_read      | 缓存读取部分                            |
| `total_token_usage.cache_write_input_tokens`    | tokens_cache_creation  | Direct copy                             |
| `session_meta.payload.git.branch`               | git_branch             | Direct copy（兜底执行 git 命令）        |
| `total_token_usage.reasoning_output_tokens`     | tokens_reasoning       | Direct copy                             |
| `"codex"`                                       | source                 | 固定为 `codex`                          |

**注意**：

- `token_count` 事件从较新的 codex-cli 版本开始写入，更早的 rollout 没有 usage 数据，脚本跳过（记 `SKIP: no usage`）。
- Codex 的 `input_tokens` 包含缓存输入，拆分为 `tokens_input`（新输入）与 `tokens_cache_read`（缓存读取），两者之和等于原始 `input_tokens`。
- `reasoning_output_tokens` 已计入 `output_tokens`，`tokens_reasoning` 仅为拆分展示，与 opencode 语义一致。


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
ses_12b7a7441ffe28fJLuv9J35Vai	2026-06-17T15:30:00+08:00\tsaveole.github.io\tdeepseek-v4-pro\t540\t18\t34412\t1746\t241280\t0\tmain\t220\topencode
```

**ZCode TSV example**（含 subagent 归并后的总消耗）：
```
sess_e66fe6bf-5468-4bfb-8fd5-c2b179b5b4b1	2026-08-03T16:16:24+08:00	mcp-gateway	GLM-5.2	5337	17	7962609	69209	7592384	0	master	0	zcode
```

**pi TSV example**（usage 字段直接映射）：
```
019fd08d-f6fa-7c92-98fe-d5140827ee22	2026-08-05T14:13:12+08:00	saveole.github.io	deepseek-v4-flash	3578	23	45130	21010	790144	0	main	8705	pi
```
