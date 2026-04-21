# TSV Data Format Specification

## Overview

Token usage data is stored as TSV (Tab-Separated Values) files with a single header line followed by one data row per session. This format replaces the previous JSONL storage to reduce file size by ~65% while preserving all essential fields.

## Column Schema

| # | Column Name             | Type    | Description                                    | Example Value                        |
|---|-------------------------|---------|------------------------------------------------|--------------------------------------|
| 1 | session_id              | string  | Unique session identifier (UUID)               | 426a4a26-94ba-401f-be63-96aa17803446 |
| 2 | timestamp               | string  | ISO 8601 UTC timestamp                         | 2026-04-15T11:48:03.018Z             |
| 3 | project                 | string  | Project name (basename of working directory)    | blog                                 |
| 4 | model                   | string  | Most frequently used model name                | glm-5.1                              |
| 5 | duration_seconds        | integer | Session duration in seconds                    | 54                                   |
| 6 | message_count           | integer | Number of deduplicated assistant messages       | 11                                   |
| 7 | tokens_input            | integer | Total input tokens consumed                    | 25195                                |
| 8 | tokens_output           | integer | Total output tokens generated                  | 1374                                 |
| 9 | tokens_cache_read       | integer | Tokens served from prompt cache (read)          | 87680                                |
| 10| tokens_cache_creation   | integer | Tokens written to prompt cache (creation)       | 0                                    |
| 11| git_branch              | string  | Git branch name at session start               | main                                 |

**Total: 11 columns, tab-delimited.**

## Removed Fields

The following field from the JSONL format is intentionally excluded (removed):

- **project_path** — removed (excluded from TSV); `project` (the directory basename) is sufficient for usage tracking. The full filesystem path is not needed for analytics.

## Header Row

Every `.data` file **must** begin with a header row containing the column names listed above, in the exact order shown, separated by tabs. The header serves as the self-describing contract for the file.

```
session_id\ttimestamp\tproject\tmodel\tduration_seconds\tmessage_count\ttokens_input\ttokens_output\ttokens_cache_read\ttokens_cache_creation\tgit_branch
```

- The header is always the **first line** of the file.
- Subsequent lines are data rows with values in the same column order.
- All 11 tab-separated fields must be present on every data row (empty strings for missing values are not expected but tolerated).

## File Naming Convention

- **Filename format**: `YYYY-MM-DD_{hostname}-{os}.data` (e.g., `2026-04-15_myhost-Linux.data`)
  - `hostname`: System hostname (from `hostname` command or `platform.node()`)
  - `os`: Operating system name (from `uname -s` or `platform.system()`, e.g., "Linux", "Darwin")
- One file per calendar day (UTC) **per device**, containing all sessions that started on that day from that device.
- **Encoding**: UTF-8, no BOM.
- **Line endings**: Unix-style (`\n`), no trailing newline at end of file.

## JSONL to TSV Field Mapping

| JSONL Field                  | TSV Column             | Transformation             |
|------------------------------|------------------------|----------------------------|
| session_id                   | session_id             | Direct copy                |
| timestamp                    | timestamp              | Direct copy                |
| project                      | project                | Direct copy                |
| project_path                 | *(removed)*            | Dropped                    |
| model                        | model                  | Direct copy                |
| duration_seconds             | duration_seconds       | Direct copy                |
| message_count                | message_count          | Direct copy                |
| tokens.input                 | tokens_input           | Flatten (nested → column)  |
| tokens.output                | tokens_output          | Flatten (nested → column)  |
| tokens.cache_read            | tokens_cache_read      | Flatten (nested → column)  |
| tokens.cache_creation        | tokens_cache_creation  | Flatten (nested → column)  |
| git_branch                   | git_branch             | Direct copy                |

## Example

**JSONL record (input)**:
```json
{"session_id": "426a4a26-94ba-401f-be63-96aa17803446", "timestamp": "2026-04-15T11:48:03.018Z", "project": "blog", "project_path": "/Users/saveole/blog", "model": "glm-5.1", "duration_seconds": 54, "message_count": 11, "tokens": {"input": 25195, "output": 1374, "cache_read": 87680, "cache_creation": 0}, "git_branch": "main"}
```

**TSV data row (output)**:
```
426a4a26-94ba-401f-be63-96aa17803446\t2026-04-15T11:48:03.018Z\tblog\tglm-5.1\t54\t11\t25195\t1374\t87680\t0\tmain
```
