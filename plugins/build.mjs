#!/usr/bin/env node
/** Build the installable plugins for Codex, Antigravity, and Claude Code,
 *  as well as the disposable dist/ package.
 *
 * `skills/model-dispatch-router` is the only editable canonical source tree.
 * Running this script generates:
 *  - dist/agentmind-model-dispatch-router/
 *  - plugins/codex/agentmind-model-dispatch-router/
 *  - plugins/antigravity/agentmind-model-dispatch-router/
 *  - plugins/claude/agentmind-model-dispatch-router/
 *  - plugins/README.md
 *
 * Platform-independent: works across Windows, macOS, and Linux without shell dependencies.
 */
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const pluginsRoot = import.meta.dirname;
const root = resolve(pluginsRoot, "..");
const sourceSkill = join(root, "skills", "model-dispatch-router");
const distOutput = join(root, "dist", "agentmind-model-dispatch-router");

if (!existsSync(sourceSkill)) {
  throw new Error(`missing canonical skill source: ${sourceSkill}`);
}

const skillFilter = (path) =>
  !/(^|[\\/])(?:\.venv|__pycache__|\.pytest_cache)(?:[\\/]|$)/.test(path) &&
  !/(^|[\\/])accounts(?:\.local)?\.sh$/.test(path);

function copySkill(destSkillDir) {
  mkdirSync(destSkillDir, { recursive: true });
  cpSync(sourceSkill, destSkillDir, {
    recursive: true,
    filter: skillFilter,
  });
}

function copyCommonFiles(destDir) {
  for (const file of ["README.md", "LICENSE"]) {
    cpSync(join(root, file), join(destDir, file));
  }
  cpSync(join(sourceSkill, "examples"), join(destDir, "examples"), { recursive: true });
}

// ---------------------------------------------------------------------------
// 1. Build plugins/codex/agentmind-model-dispatch-router
// ---------------------------------------------------------------------------
const codexPluginDir = join(pluginsRoot, "codex", "agentmind-model-dispatch-router");
rmSync(codexPluginDir, { recursive: true, force: true });
mkdirSync(join(codexPluginDir, ".codex-plugin"), { recursive: true });
copySkill(join(codexPluginDir, "skills", "model-dispatch-router"));
copyCommonFiles(codexPluginDir);

const codexManifest = {
  name: "agentmind-model-dispatch-router",
  version: "0.2.0",
  description: "Reviewable model dispatch with AgentMind code-linked memory and verification gates for OpenAI Codex.",
  author: {
    name: "AgentMind"
  },
  skills: "./skills/",
  interface: {
    displayName: "AgentMind Model Dispatch",
    shortDescription: "Dispatch work in reviewable worktrees with code-linked memory.",
    longDescription: "Model Dispatch keeps isolated task work reviewable while AgentMind supplies relevant repository context and promotes claims only after local verification.",
    developerName: "AgentMind",
    category: "Productivity",
    capabilities: [
      "Skills",
      "MCP"
    ],
    defaultPrompt: "Set up AgentMind Model Dispatch for this repository."
  },
  mcpServers: "./.mcp.json"
};
writeFileSync(join(codexPluginDir, ".codex-plugin", "plugin.json"), JSON.stringify(codexManifest, null, 2) + "\n");

const codexMcp = {
  mcpServers: {
    agentmind: {
      command: "agentmind-mcp"
    }
  }
};
writeFileSync(join(codexPluginDir, ".mcp.json"), JSON.stringify(codexMcp, null, 2) + "\n");

writeFileSync(join(codexPluginDir, ".build-info.json"), JSON.stringify({
  platform: "codex",
  source: "skills/model-dispatch-router",
  generatedAt: new Date().toISOString(),
}, null, 2) + "\n");
console.log(`[codex] built: ${codexPluginDir}`);

// ---------------------------------------------------------------------------
// 2. Build plugins/antigravity/agentmind-model-dispatch-router
// ---------------------------------------------------------------------------
const agyPluginDir = join(pluginsRoot, "antigravity", "agentmind-model-dispatch-router");
rmSync(agyPluginDir, { recursive: true, force: true });
mkdirSync(agyPluginDir, { recursive: true });
copySkill(join(agyPluginDir, "skills", "model-dispatch-router"));
copyCommonFiles(agyPluginDir);

const agyManifest = {
  name: "agentmind-model-dispatch-router",
  version: "0.2.0",
  description: "Reviewable model dispatch with AgentMind code-linked memory and verification gates for Google Antigravity (AGY).",
  author: "AgentMind",
  skills: ["skills/model-dispatch-router"],
  mcpServers: "./mcp_config.json",
  hooks: "./hooks.json"
};
writeFileSync(join(agyPluginDir, "plugin.json"), JSON.stringify(agyManifest, null, 2) + "\n");

const agyMcp = {
  mcpServers: {
    agentmind: {
      command: "agentmind-mcp"
    }
  }
};
writeFileSync(join(agyPluginDir, "mcp_config.json"), JSON.stringify(agyMcp, null, 2) + "\n");

const agyHooks = {
  hooks: {
    SessionStart: [
      {
        type: "command",
        command: "am hooks-run session-start"
      }
    ],
    SessionEnd: [
      {
        type: "command",
        command: "am hooks-run session-end"
      }
    ]
  }
};
writeFileSync(join(agyPluginDir, "hooks.json"), JSON.stringify(agyHooks, null, 2) + "\n");

writeFileSync(join(agyPluginDir, ".build-info.json"), JSON.stringify({
  platform: "antigravity",
  source: "skills/model-dispatch-router",
  generatedAt: new Date().toISOString(),
}, null, 2) + "\n");
console.log(`[antigravity] built: ${agyPluginDir}`);

// ---------------------------------------------------------------------------
// 3. Build plugins/claude/agentmind-model-dispatch-router
// ---------------------------------------------------------------------------
const claudePluginDir = join(pluginsRoot, "claude", "agentmind-model-dispatch-router");
rmSync(claudePluginDir, { recursive: true, force: true });
mkdirSync(join(claudePluginDir, ".claude-plugin"), { recursive: true });
mkdirSync(join(claudePluginDir, "hooks"), { recursive: true });
copySkill(join(claudePluginDir, "skills", "model-dispatch-router"));
copyCommonFiles(claudePluginDir);

const claudeManifest = {
  name: "agentmind-model-dispatch-router",
  version: "0.2.0",
  description: "Reviewable model dispatch with AgentMind code-linked memory and verification gates for Claude Code.",
  author: {
    name: "AgentMind"
  },
  skills: "./skills/",
  mcpServers: "./.mcp.json",
  hooks: "./hooks/hooks.json"
};
writeFileSync(join(claudePluginDir, ".claude-plugin", "plugin.json"), JSON.stringify(claudeManifest, null, 2) + "\n");

const claudeMcp = {
  mcpServers: {
    agentmind: {
      command: "agentmind-mcp"
    }
  }
};
writeFileSync(join(claudePluginDir, ".mcp.json"), JSON.stringify(claudeMcp, null, 2) + "\n");

const claudeHooks = {
  SessionStart: [
    {
      command: "am hooks-run session-start"
    }
  ],
  SessionEnd: [
    {
      command: "am hooks-run session-end"
    }
  ]
};
writeFileSync(join(claudePluginDir, "hooks", "hooks.json"), JSON.stringify(claudeHooks, null, 2) + "\n");

writeFileSync(join(claudePluginDir, ".build-info.json"), JSON.stringify({
  platform: "claude",
  source: "skills/model-dispatch-router",
  generatedAt: new Date().toISOString(),
}, null, 2) + "\n");
console.log(`[claude] built: ${claudePluginDir}`);

// ---------------------------------------------------------------------------
// 4. Build dist/ package (disposable legacy/dist package)
// ---------------------------------------------------------------------------
rmSync(distOutput, { recursive: true, force: true });
mkdirSync(distOutput, { recursive: true });
cpSync(codexPluginDir, distOutput, { recursive: true });

writeFileSync(join(distOutput, ".build-info.json"), JSON.stringify({
  source: "skills/model-dispatch-router",
  target: "dist",
  generatedAt: new Date().toISOString(),
}, null, 2) + "\n");
console.log(`[dist] built: ${distOutput}`);

// ---------------------------------------------------------------------------
// 5. Generate plugins/README.md
// ---------------------------------------------------------------------------
const pluginsReadme = `# 🧩 Model Dispatch Router Plugins

Bu dizin, **Model Dispatch Router & AgentMind** çekirdeğinin farklı AI orkestratörleri için önceden paketlenmiş, "tak-kullan" eklenti (plugin) dağıtımlarını içerir.

Tüm eklentiler ana kaynak olan \`skills/model-dispatch-router\` dizininden \`node plugins/build.mjs\` ile otomatik derlenir.

---

## 📁 Dizin Yapısı

\`\`\`text
plugins/
├── build.mjs                                # Saf paket derleyici (CI/CD uyumlu)
├── install.mjs                              # Kurulum ve senkronizasyon CLI
├── platforms/                               # Platform adaptörleri (codex, claude, antigravity)
├── lib/                                     # Ortak araçlar (paths, copy, logger)
│
├── codex/
│   └── agentmind-model-dispatch-router/     # OpenAI Codex CLI için eklenti
├── antigravity/
│   └── agentmind-model-dispatch-router/     # Google Antigravity (AGY) için eklenti
└── claude/
    └── agentmind-model-dispatch-router/     # Anthropic Claude Code için eklenti
\`\`\`

---

## 🚀 Kurulum ve Kullanım

### Otomatik Kurulum & Senkronizasyon
\`\`\`bash
# Nereye ne yazılacağını görmek için (güvenli önizleme):
npm run install:local -- --dry-run

# Yalnızca kurulu platformları güncelle (izinsiz dosya açmaz):
npm run sync

# Tüm tespit edilen araçlara ilk kurulumu yap:
npm run install:local
\`\`\`

### Manuel Kurulum

#### 1. OpenAI Codex
\`\`\`bash
cp -r plugins/codex/agentmind-model-dispatch-router ~/.codex/plugins/personal/
\`\`\`
Veya:
\`\`\`powershell
.\\sync-model-dispatch-router-skill.ps1
\`\`\`

#### 2. Google Antigravity (AGY)
- **Global:** \`plugins/antigravity/agentmind-model-dispatch-router\` klasörünü \`~/.gemini/config/plugins/\` altına kopyalayın.
- **Proje Bazlı:** İlgili projenin \`.agents/plugins/\` altına kopyalayın.

#### 3. Anthropic Claude Code
\`\`\`bash
am hooks-install . --platform claude
\`\`\`
Veya \`plugins/claude/agentmind-model-dispatch-router\` dizinini Claude plugin yolunuza ekleyin.

---

## 🔄 Yeniden Derleme (Build)

Kaynak kodda (\`skills/model-dispatch-router\`) yapılan bir değişiklikten sonra tüm eklentileri tek komutla güncellemek için:

\`\`\`bash
npm run build
# veya: node plugins/build.mjs
\`\`\`
`;

writeFileSync(join(pluginsRoot, "README.md"), pluginsReadme);
console.log("\nAll plugins successfully built and synchronized!");

if (process.argv.includes("--install")) {
  console.log("\n[build] --install flag detected. Triggering local installation...");
  const { runInstall } = await import("./install.mjs");
  await runInstall({ targetPlatform: "all", syncOnly: false });
}
