/**
 * pi coding agent Token Usage Tracker — extension
 *
 * 在 session_shutdown(退出 pi / /new / /resume / /fork / /clone)时,
 * 以 detached 子进程触发 log-usage-pi.py(hook 模式,单会话 + 节流),
 * 将本会话 token 用量写入 token-usage/YYYY-MM-DD_{hostname}-{os}.data 并 git 同步。
 *
 * 安装:复制本文件到 ~/.pi/agent/extensions/token-usage-pi/index.ts,
 * 重启 pi(或 /reload)生效。详见 token-usage/plugins/pi/README.md
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.on("session_shutdown", async (_event, ctx) => {
    try {
      const sessionFile = ctx.sessionManager.getSessionFile();
      if (!sessionFile) {
        return; // --no-session ephemeral 模式,不记录
      }

      const repoDir =
        process.env.TOKEN_USAGE_REPO_DIR ?? join(homedir(), "blog", "saveole.github.io");
      const script = join(repoDir, "token-usage", "scripts", "log-usage-pi.py");
      if (!existsSync(script)) {
        return;
      }

      // detached + unref:不阻塞 pi 退出,后台完成统计与 git 同步
      const child = spawn("python3", [script, "--session-file", sessionFile], {
        detached: true,
        stdio: "ignore",
        cwd: repoDir,
      });
      child.unref();
    } catch {
      // 统计失败绝不影响 pi 正常关闭
    }
  });
}
