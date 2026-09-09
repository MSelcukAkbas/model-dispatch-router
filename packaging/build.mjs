#!/usr/bin/env node
/** Build the installable plugin from the canonical source tree.
 *
 * `skills/model-dispatch-router` is the only editable implementation.  The output is
 * intentionally disposable: never edit dist/ or an installed plugin cache.
 */
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const sourceSkill = join(root, "skills", "model-dispatch-router");
const packageTemplate = join(root, "packaging", "agentmind-model-dispatch-router");
const output = join(root, "dist", "agentmind-model-dispatch-router");

for (const required of [sourceSkill, packageTemplate]) {
  if (!existsSync(required)) throw new Error(`missing build input: ${required}`);
}
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
cpSync(packageTemplate, output, { recursive: true });
cpSync(sourceSkill, join(output, "skills", "model-dispatch-router"), {
  recursive: true,
  filter: (path) => !/(^|[\\/])(?:\.venv|__pycache__|\.pytest_cache)(?:[\\/]|$)/.test(path)
    && !/(^|[\\/])accounts(?:\.local)?\.sh$/.test(path),
});
for (const file of ["README.md", "LICENSE"]) cpSync(join(root, file), join(output, file));
cpSync(join(packageTemplate, "examples", "model-dispatch-router.example.json"), join(output, "examples", "model-dispatch-router.example.json"));

const manifestPath = join(output, ".codex-plugin", "plugin.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
if (manifest.name !== "agentmind-model-dispatch-router" || manifest.skills !== "./skills/") {
  throw new Error("invalid plugin manifest generated");
}
for (const required of ["SKILL.md", "scripts/dispatch.sh", "mcp/agentmind/pyproject.toml"]) {
  if (!existsSync(join(output, "skills", "model-dispatch-router", required))) {
    throw new Error(`plugin is missing required skill file: ${required}`);
  }
}
writeFileSync(join(output, ".build-info.json"), JSON.stringify({
  source: "skills/model-dispatch-router",
  generatedAt: new Date().toISOString(),
}, null, 2) + "\n");
console.log(`built ${output}`);
