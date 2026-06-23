# token-usage

> Claude Code & OpenCode 会话 token 用量追踪

自动记录每次 AI 编码助手会话结束后的 token 消耗数据。目前支持 **Claude Code** 和 **OpenCode** 两个来源，写入统一的 TSV 文件。

## 工作原理

```
Claude Code 退出（SessionEnd Hook）
    ↓ log-usage.py 触发
    ↓ 从 ~/.claude/projects/<project>/<session>.jsonl 读取会话数据（ccusage 兼容方式）
    ↓ 按 message.id 去重，累加 token 用量
    ↓ 追加到 YYYY-MM-DD_{hostname}-{os}.data（按天+设备分文件，TSV 格式）
    ↓ 自动 git commit + push
    ↓ 后台启动 incremental.py
    ↓ 扫描全部 JSONL，补录缺失的历史 session（仅 append，不碰 git）
    ↓ 补录的数据在下次 hook 触发时随 git add/commit/push 一起提交
────────────────────────────
OpenCode session.updated（Plugin）
    ↓ tokentracker.js 触发
    ↓ 调用 log-usage-opencode.py
    ↓ 从 ~/.local/share/opencode/opencode.db (SQLite) 读取 session 表
    ↓ 已预聚合 token，直接映射到 TSV 格式
    ↓ 按 session_id 去重
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
- Python 3.10+ 已安装
- Git 已配置 push 权限（SSH key 或 HTTPS token）

### 第 1 步：克隆仓库

```bash
git clone https://github.com/saveole/saveole.github.io.git ~/blog/saveole.github.io
```

### 第 2 步：复制 hook 脚本

```bash
mkdir -p ~/.claude/hooks
cp ~/blog/saveole.github.io/token-usage/scripts/log-usage.py ~/.claude/hooks/log-usage.py
chmod +x ~/.claude/hooks/log-usage.py
```

### 第 3 步：修改配置

打开 `~/.claude/hooks/log-usage.py`，修改顶部配置区的仓库路径：

```python
# 修改为你的实际仓库路径
REPO_DIR = Path(os.environ.get("TOKEN_USAGE_REPO_DIR", str(Path.home() / "blog" / "saveole.github.io")))
```

如果你把仓库克隆到了其他位置，可以设置环境变量 `TOKEN_USAGE_REPO_DIR`，或直接修改代码中的路径。

### 第 4 步：注册 SessionEnd Hook

打开 `~/.claude/settings.local.json`（如不存在则创建），在 `hooks` 中添加 `SessionEnd` 配置：

> ⚠️ **务必注册到 `settings.local.json`，不要写到 `settings.json`。** 若你使用 GLM / 第三方代理（如 bigmodel），那套代理配置工具会**整段重写 `~/.claude/settings.json`**，每次重写都会把 `hooks` 段冲掉，导致 token 追踪悄悄失效（此问题已多次复现）。`settings.local.json` 是 Claude Code 的本地个人设置文件，会与 `settings.json` 合并生效，且代理工具通常不碰它——把 hook 放在这里才能持久。

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/env node ~/.tokentracker/bin/notify.cjs --source=claude"
          },
          {
            "type": "command",
            "command": "python3 ~/blog/saveole.github.io/token-usage/scripts/log-usage.py",
            "timeout": 10000
          }
        ]
      }
    ]
  }
}
```

- **log-usage.py**：Claude Code 退出时触发，从 JSONL 读取会话数据，记录 token 用量并 git 同步。
- **notify.cjs**：tokentracker 通知脚本，写入信号文件并节流触发远程同步（最多 20 秒一次）。

如果 `settings.local.json` 中已有其他配置（如 `permissions`），只需把 `hooks` 键合并进去即可，不要覆盖已有内容：

```json
{
  "permissions": { "...已有内容保持不变..." },
  "hooks": {
    "SessionEnd": [ /* 同上 */ ]
  }
}
```

### 第 5 步：回填历史数据（可选）

如果你在安装 hook 之前已经使用 Claude Code 一段时间，可以用回填脚本一次性导入历史会话数据：

```bash
python3 ~/blog/saveole.github.io/token-usage/scripts/backfill.py
```

脚本会扫描 `~/.claude/projects/` 下所有 JSONL 文件，提取 token 用量并写入 TSV 文件。**增量设计**：已记录的 session 会自动跳过，已有但 token 不同的 session 会原地更新，不会删除其他机器记录的数据。回填完成后会自动运行 `aggregate.py` 打印汇总统计。

此外，hook 脚本在每次会话结束后会自动后台运行 `incremental.py`，扫描所有 JSONL 并补录缺失的 session。因此正常使用中无需手动回填，`backfill.py` 仅在首次安装时需要运行一次。

> **注意：** 回填范围受 Claude Code 本地数据保留期限限制（默认 30 天，见下方「数据保留说明」）。超过保留期的 JSONL 文件已被自动清理，无法回填。因此建议尽早安装 hook 进行持续记录。

### 第 6 步：验证

开始并结束一次 Claude Code 会话，然后检查：

```bash
# 应该能看到当天生成的 .data 文件（文件名包含主机名和系统）
ls ~/blog/saveole.github.io/token-usage/$(date -u +%Y-%m-%d)_*.data

# 查看记录内容（TSV 格式）
cat ~/blog/saveole.github.io/token-usage/$(date -u +%Y-%m-%d)_*.data
```

如果 `.data` 文件存在且包含 TSV header + 数据行，说明配置成功。

## 安装 OpenCode 插件

### 前提条件

- [OpenCode](https://opencode.ai) 已安装
- 上述 Claude Code 安装步骤已完成（共用同一个仓库）
- OpenCode 配置文件目录 `~/.config/opencode/plugin/` 已存在（首次安装 OpenCode 后自动创建）

### 第 1 步：检查脚本文件

确认 `log-usage-opencode.py` 在仓库中（克隆时已包含）：

```bash
ls ~/blog/saveole.github.io/token-usage/scripts/log-usage-opencode.py
```

### 第 2 步：注册 OpenCode 插件

OpenCode 自动加载 `~/.config/opencode/plugin/` 目录下的 `.js` 文件作为插件。插件文件 `tokentracker.js` 已经存在，需要确认其中路径配置正确。

打开 `~/.config/opencode/plugin/tokentracker.js`，确认脚本路径指向正确位置：

```js
const logScript = "/home/ant/blog/saveole.github.io/token-usage/scripts/log-usage-opencode.py";
```

如果你的仓库在其他位置，修改此路径即可。

### 第 3 步：验证插件已注册

```bash
opencode debug config | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('plugin',[]))"
```

应看到输出中包含 `file:///home/ant/.config/opencode/plugin/tokentracker.js`，表示插件已加载。

### 触发器机制

```
opencode TUI 会话更新
    ↓
session.updated event 触发
    ↓
tokentracker.js 插件（30s 节流防抖）
    ↓
python3 log-usage-opencode.py --since 30
    ↓
查询 ~/.local/share/opencode/opencode.db (SQLite)
    ↓ session 表已预聚合 token，直接映射
写入 YYYY-MM-DD_{hostname}-{os}.data (TSV)
    ↓
git add → commit → pull --rebase → push
```

- **触发时机**：每次 opencode 会话中 token 数据更新时（如 assistant 回复后），opencode 内部触发 `session.updated` 事件
- **节流**：插件通过 `fired` 标志实现 30 秒节流，避免短时间内重复触发
- **去重**：`log-usage-opencode.py` 会按 `session_id` + token 数量判断是否已有记录，相同数据不重复写入
- **SQLite 优势**：OpenCode 的 `session` 表已预先聚合 token 统计（`tokens_input`, `tokens_output`, `tokens_reasoning`, `tokens_cache_read`, `tokens_cache_write`），无需像 Claude Code 那样逐行解析 JSONL

### 第 4 步：验证

开始一次 OpenCode 会话，和 AI 对话几轮后，检查：

```bash
# 查看日志
tail -20 ~/.claude/hooks/tracker.log | grep opencode

# 查看当天记录（应能看到 source=opencode 的行）
grep "opencode" ~/blog/saveole.github.io/token-usage/$(date +%Y-%m-%d)_*.data
```

### 手动补录历史数据

如果需要一次性导入所有已有 OpenCode 会话数据（首次安装后），直接运行脚本即可（不带 `--since` 参数会扫描全部 session）：

```bash
python3 ~/blog/saveole.github.io/token-usage/scripts/log-usage-opencode.py
```

脚本去重逻辑会跳过已记录的 session，只写入新增和变动的数据。

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
│   ├── log-usage.py          # Claude Code Hook 脚本（Python，复制到 ~/.claude/hooks/ 使用）
│   ├── log-usage-opencode.py # OpenCode Plugin 脚本（Python，由 tokentracker.js 调用）
│   ├── incremental.py        # 轻量增量补录（hook 后台调用，仅 append，不碰 git）
│   ├── aggregate.py          # 终端诊断脚本（仅打印汇总，不写文件）
│   └── backfill.py           # 全量历史回填（增量 merge，含 git 操作，首次安装用）
├── SCHEMA.md                 # TSV 格式规范
├── .gitignore                # 忽略已废弃的 daily-summary.json / REPORT.md
└── README.md                 # 本文件
```

## 数据格式

每条 TSV 记录（13 列，tab 分隔）：

```
session_id   timestamp   project   model   duration_seconds   message_count   tokens_input   tokens_output   tokens_cache_read   tokens_cache_creation   git_branch   tokens_reasoning   source
```

**示例数据行：**

```
426a4a26-94ba-401f-be63-96aa17803446	2026-04-15T09:48:23Z	skills	glm-5.1	1844	17	112264	19600	2632000	0	main	0	claude
ses_12b7a7441ffe28fJLuv9J35Vai	2026-06-17T15:30:00+08:00	blog	deepseek-v4-pro	540	18	34412	1746	241280	0	main	220	opencode
```

| 字段 | 说明 |
|------|------|
| `session_id` | 会话唯一标识 |
| `timestamp` | 记录时间（CST +08:00） |
| `project` | 项目名 |
| `model` | 使用的模型 |
| `duration_seconds` | 会话时间跨度 |
| `message_count` | 消息数 |
| `tokens_input` | 输入 token 数 |
| `tokens_output` | 输出 token 数 |
| `tokens_cache_read` | 缓存读取 token 数 |
| `tokens_cache_creation` | 缓存写入 token 数 |
| `git_branch` | 会话时的 git 分支 |
| `tokens_reasoning` | 推理（thinking）token 数（OpenCode 特有） |
| `source` | 数据来源：claude / opencode |

完整规范见 [SCHEMA.md](./SCHEMA.md)。

## 数据保留说明

### Claude Code

本工具的数据来源依赖于 Claude Code 本地存储的会话 JSONL 文件（`~/.claude/projects/<project>/<session>.jsonl`）。Claude Code 默认保留 **30 天**的本地数据，到期后自动清理。

| 数据类型 | 默认保留期 | 说明 |
|----------|-----------|------|
| 会话 JSONL（`.jsonl`） | 30 天 | hook 和回填脚本的唯一数据来源 |
| 工具结果缓存 | 30 天 | 随 JSONL 一起清理 |

可通过 `~/.claude/settings.json` 中的 `cleanupPeriodDays` 调整保留期限：
```json
{ "cleanupPeriodDays": 90 }
```

### OpenCode

数据来源为 OpenCode 本地 SQLite 数据库（`~/.local/share/opencode/opencode.db`）。**OpenCode 不做自动清理**，`session` 和 `message` 表会持续累积。`log-usage-opencode.py` 直接查询预聚合的 token 统计，其历史数据范围与 SQLite DB 一致。

对本工具的影响：

- **Hook / Plugin 实时记录**：不受影响。hook/plugin 立即从本地数据提取 token 写入 TSV，不依赖历史数据。
- **回填历史数据**：Claude Code 只能回填保留期内未被清理的 JSONL；OpenCode 可回填 SQLite 中所有历史 session。
- **仓库的 .data 文件**：不受任何工具清理机制影响，除非你手动删除，否则永久保留在 git 历史中。

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
| 会话结束后没有 .data 文件 | 确认 Python 3.10+ 已安装：`python3 --version` |
| .data 文件存在但没有 push | 查看 `~/.claude/hooks/tracker-errors.log` 中的错误日志 |
| settings 不生效 | 确认 JSON 格式正确：`python3 -m json.tool ~/.claude/settings.local.json` |
| hook 又不工作了（曾正常过） | 多半是 `settings.json` 被代理配置工具整段重写、`hooks` 段被冲掉。确认 hook 在 `settings.local.json` 而非 `settings.json`（详见「第 4 步」） |
| 同一会话记录了两条 | 正常不会出现。hook 脚本按 `session_id` 去重 |
| 找不到 JSONL 文件 | 确认 `~/.claude/projects/` 目录存在且有 `.jsonl` 文件；或设置 `CLAUDE_CONFIG_DIR` 环境变量指定数据目录 |

### OpenCode

| 现象 | 检查 |
|------|------|
| 会话结束后没有记录 | 确认插件已注册：`opencode debug config \| python3 -c "import sys,json; print(json.load(sys.stdin).get('plugin',[]))"` |
| 插件注册了但没有 .data 文件 | 查看 `~/.claude/hooks/tracker.log` 中 `START` / `SKIP` 开头的行，确认脚本是否被触发 |
| .data 文件存在但没有 push | 查看日志中 `GIT:` 开头的行；检查仓库 git remote 配置 |
| project 列显示 `unknown` | DB 中 session 未关联 project，fallback 到了目录 basename，正常 |
| 零 token 会话被跳过 | 正常 — 脚本只记录 `input > 0 OR output > 0` 的 session |
| reasoning 列为 0 | 部分模型不支持 reasoning / thinking，该列为 0 是正常的 |

### Hermes Agent

| 现象 | 检查 |
|------|------|
| 退出后没有记录 | 确认 `~/.hermes/plugins/token-usage/` 包含 `plugin.yaml` 和 `__init__.py` |
| 有记录但没 push | 查看 `~/.hermes/plugins/token-usage-tracker.log` 中 GIT 开头的行 |
| project 显示 "unknown" | Hermes sessions 表不存 cwd，插件 fallback 到 `os.getcwd()` 的 basename |
| 零 token 会话被跳过 | 正常行为 — input=0 且 output=0 的会话不记录 |
