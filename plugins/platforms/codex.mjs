import { existsSync, rmSync } from "node:fs";
import { join } from "node:path";
import { PLATFORM_PATHS } from "../lib/paths.mjs";
import { syncDirectory } from "../lib/copy.mjs";
import { logger } from "../lib/logger.mjs";

export const name = "codex";
export const displayName = "OpenAI Codex";

export function detect() {
  return existsSync(PLATFORM_PATHS.codex.base);
}

export function isInstalled() {
  const cacheInstalls = PLATFORM_PATHS.codex.findCacheInstallations();
  const canonicalPlugin = join(PLATFORM_PATHS.codex.plugins, "personal", "agentmind-model-dispatch-router");
  return cacheInstalls.length > 0 || existsSync(canonicalPlugin);
}

export function install(sourceDir, options = {}) {
  const { dryRun = false } = options;
  if (!detect()) {
    logger.warn(`Codex base directory not found at ${PLATFORM_PATHS.codex.base}`);
    return false;
  }

  let installedAny = false;

  // 1. Canonical plugin directory
  const canonicalPlugin = join(PLATFORM_PATHS.codex.plugins, "personal", "agentmind-model-dispatch-router");
  logger.info(`Installing Codex plugin to canonical path: ${canonicalPlugin}`);
  syncDirectory(sourceDir, canonicalPlugin, { dryRun });
  installedAny = true;

  // 2. Also sync to active cache installations if they exist
  const cacheInstalls = PLATFORM_PATHS.codex.findCacheInstallations();
  for (const cacheDir of cacheInstalls) {
    const targetSkill = join(cacheDir, "skills", "model-dispatch-router");
    const sourceSkill = join(sourceDir, "skills", "model-dispatch-router");
    logger.info(`Syncing active Codex cache at: ${cacheDir}`);
    syncDirectory(sourceSkill, targetSkill, { dryRun });
  }

  if (!dryRun) {
    logger.success("Codex plugin installation / sync complete.");
  }
  return installedAny;
}

export function update(sourceDir, options = {}) {
  if (!isInstalled()) {
    logger.warn("Codex plugin is not installed; skipping update (run install to initialize).");
    return false;
  }
  return install(sourceDir, options);
}

export function uninstall(options = {}) {
  const { dryRun = false } = options;
  const canonicalPlugin = join(PLATFORM_PATHS.codex.plugins, "personal", "agentmind-model-dispatch-router");
  if (existsSync(canonicalPlugin)) {
    if (dryRun) {
      logger.dryRun(`Would remove ${canonicalPlugin}`);
    } else {
      rmSync(canonicalPlugin, { recursive: true, force: true });
      logger.success(`Removed ${canonicalPlugin}`);
    }
  }
}
