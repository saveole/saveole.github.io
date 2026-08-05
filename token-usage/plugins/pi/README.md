# pi 扩展:token 用量追踪

pi coding agent 的 token 用量追踪扩展。在 `session_shutdown` 时以 detached 子进程触发
[`log-usage-pi.py`](../../scripts/log-usage-pi.py),将本会话 token 消耗写入
`token-usage/YYYY-MM-DD_{hostname}-{os}.data`(与其他 agent 相同的 13 列 TSV 格式),
并自动 git commit + push。

## 工作原理

```
pi 退出 / /new / /resume / /fork / /clone
    ↓ session_shutdown 事件
index.ts(本扩展)
    ↓ spawn python3 log-usage-pi.py --session-file <会话文件>(detached,不阻塞退出)
读取 ~/.pi/agent/sessions/**/*.jsonl 中该会话
    ↓ 累加 assistant / toolResult 内嵌 / compaction / branch_summary 的 usage
    ↓ 进程内节流(默认 5 分钟,PI_THROTTLE_MINUTES 可调)
写入 YYYY-MM-DD_{hostname}-{os}.data (TSV,按 session_id 去重/更新)
    ↓ git add → commit → pull --rebase → push
```

- **数据源**:pi 的会话 JSONL 直接携带 `usage` 字段
  (`input` / `output` / `cacheRead` / `cacheWrite` / `reasoning` / `totalTokens` / `cost`),
  无需解析嵌套结构或估算,与 pi footer 显示的总量一致。
- **触发时机**:`session_shutdown` 在退出、切换会话、fork/clone 时都会触发。
- **节流**:statefile `~/.pi/tracker-throttle.json`(`PI_THROTTLE_FILE` 可改),
  同一 session 距上次记录 < 5 分钟直接 return,避免频繁 commit + push。
  兜底:节流期间错过的数据会在下次任何会话触发 `--since`/`--all` 补录时拉平。
- **去重**:按 `session_id` + 5 个 token 字段判断,相同数据不重复写入。
- **ephemeral 模式**(`--no-session`)不记录。

## 安装

### 第 1 步:复制扩展

```bash
mkdir -p ~/.pi/agent/extensions/token-usage-pi
cp ~/blog/saveole.github.io/token-usage/plugins/pi/index.ts ~/.pi/agent/extensions/token-usage-pi/
```

### 第 2 步:重启 pi 生效

扩展在 pi 启动时加载。重启 pi,或在新会话中输入 `/reload` 重新加载扩展。

### 第 3 步:验证

退出一次 pi 会话,然后检查:

```bash
# 查看日志(应有 [pi] START / NEW / GIT 开头的行)
tail -20 ~/.claude/hooks/tracker.log | grep pi

# 查看当天记录(应能看到 source=pi 的行)
grep "pi$" ~/blog/saveole.github.io/token-usage/$(date +%Y-%m-%d)_*.data
```

### 手动补录历史数据

首次安装后一次性导入所有已有 pi 会话数据:

```bash
python3 ~/blog/saveole.github.io/token-usage/scripts/log-usage-pi.py --all
```

脚本去重逻辑会跳过已记录的 session,只写入新增和变动的数据。

## 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `TOKEN_USAGE_REPO_DIR` | `~/blog/saveole.github.io` | 追踪仓库路径 |
| `PI_SESSION_DIR` | `~/.pi/agent/sessions` | pi 会话数据目录 |
| `PI_THROTTLE_MINUTES` | `5` | 同一 session 节流窗口(分钟) |
| `PI_THROTTLE_FILE` | `~/.pi/tracker-throttle.json` | 节流 statefile |

## 故障排查

| 现象 | 检查 |
|------|------|
| 退出后没有记录 | 确认扩展已加载:`~/.pi/agent/extensions/token-usage-pi/index.ts` 存在,重启 pi 或 `/reload` |
| 扩展加载了但没有 .data 文件 | 查看 `~/.claude/hooks/tracker.log` 中 `[pi]` 开头的行,确认 SKIP 原因(节流 / 无 usage / 文件不存在) |
| .data 文件存在但没有 push | 查看日志中 `GIT:` 开头的行;检查仓库 git remote 配置 |
| project 列显示 unknown | session header 无 `cwd` 字段时 fallback,正常 |
| 零 token 会话被跳过 | 正常 — 脚本只记录 `input > 0 OR output > 0` 的会话 |
