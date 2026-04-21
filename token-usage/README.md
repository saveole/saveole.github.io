# token-usage

> Claude Code & Hermes Agent 会话 token 用量追踪

自动记录每次 AI 编码助手会话结束后的 token 消耗数据。目前支持 **Claude Code** 和 **Hermes Agent** 两个来源，写入统一的 TSV 文件。

## 工作原理

```
Claude Code 会话结束
    ↓ Stop Hook 触发
    ↓ 解析会话 transcript，按 message.id 去重，累加 token 用量
    ↓ 追加到 YYYY-MM-DD_{hostname}-{os}.data（按天+设备分文件，TSV 格式）
    ↓ 自动 git commit + push
    ↓ 后台启动 incremental.py
    ↓ 扫描全部 transcript，补录缺失的历史 session（仅 append，不碰 git）
    ↓ 补录的数据在下次 hook 触发时随 git add/commit/push 一起提交
────────────────────────────
Hermes Agent 会话结束
    ↓ on_session_finalize Plugin hook 触发
    ↓ 从 state.db 读取 session token 统计
    ↓ 追加到同一天的 YYYY-MM-DD_{hostname}-{os}.data（同一 TSV 文件）
    ↓ 自动 git commit + push
────────────────────────────
博客构建（node build.js）
    ↓ 直接读取所有 YYYY-MM-DD_*.data 文件
    ↓ 按 session_id 去重，按日聚合 token
    ↓ 生成热力图数据，渲染到首页
```

## 安装

### 前提条件

- [Claude Code](https://claude.ai/code) 已安装并登录
- [jq](https://jqlang.github.io/jq/) 已安装（`brew install jq` / `apt install jq`）
- Git 已配置 push 权限（SSH key 或 HTTPS token）

### 第 1 步：克隆仓库

```bash
git clone https://github.com/saveole/saveole.github.io.git ~/blog/saveole.github.io
```

### 第 2 步：复制 hook 脚本

```bash
mkdir -p ~/.claude/hooks
cp ~/blog/saveole.github.io/token-usage/scripts/log-usage.sh ~/.claude/hooks/log-usage.sh
chmod +x ~/.claude/hooks/log-usage.sh
```

### 第 3 步：修改配置

打开 `~/.claude/hooks/log-usage.sh`，修改顶部配置区的仓库路径：

```bash
# 修改为你的实际仓库路径
REPO_DIR="$HOME/blog/saveole.github.io"
```

如果你把仓库克隆到了其他位置，改为对应路径即可。

### 第 4 步：注册 Stop Hook

打开 `~/.claude/settings.json`（如不存在则创建），在 `hooks` 中添加 `Stop` 配置：

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/log-usage.sh"
          }
        ]
      }
    ]
  }
}
```

如果 `settings.json` 中已有其他 hooks 配置（如 `PreToolUse`），只需将 `Stop` 数组追加到 `hooks` 对象中即可，不要覆盖已有配置。

### 第 5 步：回填历史数据（可选）

如果你在安装 hook 之前已经使用 Claude Code 一段时间，可以用回填脚本一次性导入历史会话数据：

```bash
python3 ~/blog/saveole.github.io/token-usage/scripts/backfill.py
```

脚本会扫描 `~/.claude/projects/` 下所有 transcript 文件，提取 token 用量并写入 TSV 文件。**增量设计**：已记录的 session 会自动跳过，已有但 token 不同的 session 会原地更新，不会删除其他机器记录的数据。回填完成后会自动运行 `aggregate.py` 打印汇总统计。

此外，hook 脚本在每次会话结束后会自动后台运行 `incremental.py`，扫描所有 transcript 并补录缺失的 session。因此正常使用中无需手动回填，`backfill.py` 仅在首次安装时需要运行一次。

> **注意：** 回填范围受 Claude Code 本地数据保留期限限制（默认 30 天，见下方「数据保留说明」）。超过保留期的 transcript 文件已被自动清理，无法回填。因此建议尽早安装 hook 进行持续记录。

### 第 6 步：验证

开始并结束一次 Claude Code 会话，然后检查：

```bash
# 应该能看到当天生成的 .data 文件（文件名包含主机名和系统）
ls ~/blog/saveole.github.io/token-usage/$(date -u +%Y-%m-%d)_*.data

# 查看记录内容（TSV 格式）
cat ~/blog/saveole.github.io/token-usage/$(date -u +%Y-%m-%d)_*.data
```

如果 `.data` 文件存在且包含 TSV header + 数据行，说明配置成功。

## 安装 Hermes Agent 插件

### 前提条件

- [Hermes Agent](https://github.com/nicepkg/hermes) 已安装
- 上述 Claude Code 安装步骤已完成（共用同一个仓库）

### 第 1 步：复制插件

```bash
mkdir -p ~/.hermes/plugins/token-usage
cp ~/blog/saveole.github.io/token-usage/plugins/hermes/__init__.py ~/.hermes/plugins/token-usage/
cp ~/blog/saveole.github.io/token-usage/plugins/hermes/plugin.yaml ~/.hermes/plugins/token-usage/
```

### 第 2 步：验证

启动 Hermes，正常使用后退出（Ctrl+C 或 `/exit`），然后检查：

```bash
# 查看插件日志
cat ~/.hermes/plugins/token-usage-tracker.log

# 查看 TSV 文件（应能看到 Hermes 格式的 session_id）
tail -1 ~/blog/saveole.github.io/token-usage/$(date -u +%Y-%m-%d)_*.data
```

详细说明见 [plugins/hermes/README.md](./plugins/hermes/README.md)。

## 目录结构

```
token-usage/
├── YYYY-MM-DD_{hostname}-{os}.data  # 每日每设备会话记录（hook/plugin 自动追加，TSV 格式）
├── plugins/
│   └── hermes/               # Hermes Agent 插件
│       ├── __init__.py       # 插件实现
│       ├── plugin.yaml       # 插件清单
│       └── README.md         # Hermes 插件文档
├── scripts/
│   ├── log-usage.sh          # Claude Code Hook 脚本（复制到 ~/.claude/hooks/ 使用）
│   ├── incremental.py        # 轻量增量补录（hook 后台调用，仅 append，不碰 git）
│   ├── aggregate.py          # 终端诊断脚本（仅打印汇总，不写文件）
│   └── backfill.py           # 全量历史回填（增量 merge，含 git 操作，首次安装用）
├── SCHEMA.md                 # TSV 格式规范
├── .gitignore                # 忽略已废弃的 daily-summary.json / REPORT.md
└── README.md                 # 本文件
```

## 数据格式

每条 TSV 记录（11 列，tab 分隔）：

```
session_id   timestamp   project   model   duration_seconds   message_count   tokens_input   tokens_output   tokens_cache_read   tokens_cache_creation   git_branch
```

**示例数据行：**

```
426a4a26-94ba-401f-be63-96aa17803446	2026-04-15T09:48:23Z	skills	glm-5.1	1844	17	112264	19600	2632000	0	main
```

| 字段 | 说明 |
|------|------|
| `session_id` | 会话唯一标识 |
| `timestamp` | 记录时间（UTC） |
| `project` | 工作目录名称 |
| `model` | 使用的模型（按使用频率取最多的） |
| `duration_seconds` | 首条 assistant 消息到末条的时间跨度 |
| `message_count` | 去重后的 assistant 消息数 |
| `tokens_input` | 输入 token 数 |
| `tokens_output` | 输出 token 数 |
| `tokens_cache_read` | 缓存读取 token 数 |
| `tokens_cache_creation` | 缓存写入 token 数 |
| `git_branch` | 会话时的 git 分支 |

完整规范见 [SCHEMA.md](./SCHEMA.md)。

## 数据保留说明

本工具的数据来源依赖于 Claude Code 本地存储的会话 transcript 文件（`~/.claude/projects/`）。Claude Code 默认保留 **30 天**的本地数据，到期后自动清理。

| 数据类型 | 默认保留期 | 说明 |
|----------|-----------|------|
| 会话 transcript（`.jsonl`） | 30 天 | 回填脚本的唯一数据来源 |
| 工具结果缓存 | 30 天 | 随 transcript 一起清理 |

可通过 `~/.claude/settings.json` 中的 `cleanupPeriodDays` 调整保留期限：

```json
{
  "cleanupPeriodDays": 90
}
```

**对本工具的影响：**

- **Hook 实时记录**：不受影响。hook 在会话结束时立即提取数据写入 TSV，不依赖历史 transcript。
- **回填历史数据**：只能回填保留期内未被清理的 transcript。如果希望保留更长的回填窗口，建议增大 `cleanupPeriodDays`。
- **仓库的 .data 文件**：不受 Claude Code 清理机制影响，除非你手动删除，否则永久保留在 git 历史中。

## 查看统计

- **博客首页**：`node build.js` 构建后，首页热力图自动展示每日 token 用量趋势
- **终端**：手动运行 `python3 ~/blog/saveole.github.io/token-usage/scripts/aggregate.py` 查看汇总

## 多机使用

在另一台电脑上重复「安装」步骤即可。每台机器会生成独立的 `{hostname}-{os}` 后缀文件，避免冲突。

**文件命名规则**：
- 格式：`YYYY-MM-DD_{hostname}-{os}.data`
- 示例：
  - `2026-04-21_desktop1-Linux.data`
  - `2026-04-21_macbook2-Darwin.data`
  - `2026-04-21_workpc-Windows.data`

这样多台机器可以同时向同一仓库 push，不会相互覆盖。博客构建脚本会自动读取所有 `{YYYY-MM-DD}_*.data` 文件并按 `session_id` 去重聚合。

## 故障排查

### Claude Code

| 现象 | 检查 |
|------|------|
| 会话结束后没有 .data 文件 | 确认 `jq` 已安装：`which jq` |
| .data 文件存在但没有 push | 查看 `~/.claude/hooks/tracker-errors.log` 中的错误日志 |
| settings.json 不生效 | 确认 JSON 格式正确：`python3 -m json.tool ~/.claude/settings.json` |
| 同一会话记录了两条 | 正常不会出现。hook 脚本按 `session_id` 去重 |

### Hermes Agent

| 现象 | 检查 |
|------|------|
| 退出后没有记录 | 确认 `~/.hermes/plugins/token-usage/` 包含 `plugin.yaml` 和 `__init__.py` |
| 有记录但没 push | 查看 `~/.hermes/plugins/token-usage-tracker.log` 中 GIT 开头的行 |
| project 显示 "unknown" | Hermes sessions 表不存 cwd，插件 fallback 到 `os.getcwd()` 的 basename |
| 零 token 会话被跳过 | 正常行为 — input=0 且 output=0 的会话不记录 |
