import { existsSync, rmSync } from "node:fs";
import { PLATFORM_PATHS } from "../lib/paths.mjs";
import { syncDirectory } from "../lib/copy.mjs";
import { logger } from "../lib/logger.mjs";

export const name = "claude";
export const displayName = "Anthropic Claude Code";

export function detect() {
  return existsSync(PLATFORM_PATHS.claude.base);
}

export function isInstalled() {
  return existsSync(PLATFORM_PATHS.claude.targetPlugin);
}

export function install(sourceDir, options = {}) {
  const { dryRun = false } = options;
  if (!detect()) {
    logger.warn(`Claude base directory not found at ${PLATFORM_PATHS.claude.base}`);
    return false;
  }

  const targetDir = PLATFORM_PATHS.claude.targetPlugin;
  logger.info(`Installing Claude Code plugin to: ${targetDir}`);
  syncDirectory(sourceDir, targetDir, { dryRun });

  if (!dryRun) {
    logger.success("Claude Code plugin installation complete.");
  }
  return true;
}

export function update(sourceDir, options = {}) {
  if (!isInstalled()) {
    logger.warn("Claude Code plugin is not installed; skipping update (run install to initialize).");
    return false;
  }
  return install(sourceDir, options);
}

export function uninstall(options = {}) {
  const { dryRun = false } = options;
  const targetDir = PLATFORM_PATHS.claude.targetPlugin;
  if (existsSync(targetDir)) {
    if (dryRun) {
      logger.dryRun(`Would remove ${targetDir}`);
    } else {
      rmSync(targetDir, { recursive: true, force: true });
      logger.success(`Removed ${targetDir}`);
    }
  }
}
