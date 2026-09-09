import { homedir } from "node:os";
import { join } from "node:path";
import { existsSync, readdirSync } from "node:fs";

export const HOME_DIR = homedir();

export const PLATFORM_PATHS = {
  codex: {
    base: join(HOME_DIR, ".codex"),
    plugins: join(HOME_DIR, ".codex", "plugins"),
    // Also check cached installations created by Codex CLI
    findCacheInstallations() {
      const cacheBase = join(HOME_DIR, ".codex", "plugins", "cache", "personal", "agentmind-model-dispatch-router");
      if (!existsSync(cacheBase)) return [];
      try {
        return readdirSync(cacheBase, { withFileTypes: true })
          .filter((d) => d.isDirectory())
          .map((d) => join(cacheBase, d.name));
      } catch {
        return [];
      }
    },
  },
  antigravity: {
    base: join(HOME_DIR, ".gemini"),
    configPlugins: join(HOME_DIR, ".gemini", "config", "plugins"),
    targetPlugin: join(HOME_DIR, ".gemini", "config", "plugins", "agentmind-model-dispatch-router"),
    globalSkills: join(HOME_DIR, ".gemini", "config", "skills", "model-dispatch-router"),
  },
  claude: {
    base: join(HOME_DIR, ".claude"),
    plugins: join(HOME_DIR, ".claude", "plugins"),
    targetPlugin: join(HOME_DIR, ".claude", "plugins", "agentmind-model-dispatch-router"),
  },
};
