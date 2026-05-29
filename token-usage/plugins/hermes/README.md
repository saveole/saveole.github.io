# Hermes token-usage Plugin

> Hermes Agent 会话 token 用量追踪插件，与 Claude Code token-usage 共享同一数据仓库和 TSV 格式。

## 工作原理

```
Hermes 会话结束（退出 CLI / /new / context compression）
    ↓ on_session_finalize hook 触发
    ↓ 从 ~/.hermes/state.db 读取 session token 统计
    ↓ 追加到 YYYY-MM-DD_{hostname}-{os}.data（与 Claude Code 同一目录）
    ↓ 自动 git commit + push
    ↓ 扫描 state.db 全部 session，补录缺失的历史 session（仅 append，不碰 git）
    ↓ 补录的数据在下次 hook 触发时随 git add/commit/push 一起提交
────────────────────────────
博客构建（node build.js）
    ↓ 直接读取所有 YYYY-MM-DD_*.data 文件
    ↓ 按 session_id 去重，按日聚合
    ↓ 生成热力图数据渲染到首页
```

## 与 Claude Code tracker 的关系

| | Claude Code | Hermes |
|---|---|---|
| 触发方式 | Stop Hook (bash 脚本) | Plugin `on_session_finalize` hook |
| 数据来源 | 解析 transcript JSONL | 查询 state.db sessions 表 |
| session_id 格式 | UUID (`c26c934d-...`) | `YYYYMMDD_HHMMSS_hex` |
| 输出格式 | TSV（同一个 `.data` 文件） | TSV（同一个 `.data` 文件） |
| 自动补录 | incremental.py（扫描 transcript） | _backfill_missing()（扫描 state.db） |
| 配置位置 | `~/.claude/hooks/log-usage.sh` | `~/.hermes/plugins/token-usage/` |

两者写入完全相同的 TSV schema（11 列），可在同一份 `.data` 文件中共存，无需额外处理。

## 安装

### 前提条件

- [Hermes Agent](https://github.com/nicepkg/hermes) 已安装
- `~/blog/saveole.github.io/` 仓库已克隆

### 第 1 步：复制插件

```bash
mkdir -p ~/.hermes/plugins/token-usage
cp ~/blog/saveole.github.io/token-usage/plugins/hermes/__init__.py ~/.hermes/plugins/token-usage/
cp ~/blog/saveole.github.io/token-usage/plugins/hermes/plugin.yaml ~/.hermes/plugins/token-usage/
```

### 第 2 步：验证

```bash
# 启动 Hermes，正常使用后退出
hermes

# 检查是否有日志输出
cat ~/.hermes/plugins/token-usage-tracker.log

# 检查 TSV 文件
tail -1 ~/blog/saveole.github.io/token-usage/$(date -u +%Y-%m-%d).data
```

### 配置

插件无需额外配置。默认将数据写入 `~/blog/saveole.github.io/token-usage/`。

如需自定义仓库路径，设置环境变量：

```bash
export TOKEN_USAGE_REPO_DIR="$HOME/your/custom/path"
```

## 目录结构

```
plugins/hermes/
├── plugin.yaml      # 插件清单（声明 hooks）
├── __init__.py      # 插件实现（数据采集 + git 同步）
└── README.md        # 本文件
```

## 日志与排查

| 文件 | 说明 |
|------|------|
| `~/.hermes/plugins/token-usage-tracker.log` | 插件运行日志（每次 hook 触发都会写入） |

常见问题：

| 现象 | 检查 |
|------|------|
| 会话结束后没有记录 | 确认 `~/.hermes/plugins/token-usage/` 目录存在且包含 `plugin.yaml` 和 `__init__.py` |
| 记录了但没有 push | 查看 `token-usage-tracker.log` 中 GIT 开头的行 |
| project 显示 "unknown" | Hermes 的 sessions 表没有存储 cwd，插件会 fallback 到 `os.getcwd()` 的 basename |
| 零 token 会话被跳过 | 正常行为 — input=0 且 output=0 的会话不记录 |
