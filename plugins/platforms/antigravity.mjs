import { existsSync, rmSync } from "node:fs";
import { join } from "node:path";
import { PLATFORM_PATHS } from "../lib/paths.mjs";
import { syncDirectory } from "../lib/copy.mjs";
import { logger } from "../lib/logger.mjs";

export const name = "antigravity";
export const displayName = "Google Antigravity (AGY)";

export function detect() {
  return existsSync(PLATFORM_PATHS.antigravity.base);
}

export function isInstalled() {
  return existsSync(PLATFORM_PATHS.antigravity.targetPlugin);
}

export function install(sourceDir, options = {}) {
  const { dryRun = false } = options;
  if (!detect()) {
    logger.warn(`Antigravity base directory not found at ${PLATFORM_PATHS.antigravity.base}`);
    return false;
  }

  const targetDir = PLATFORM_PATHS.antigravity.targetPlugin;
  logger.info(`Installing Antigravity plugin to: ${targetDir}`);
  syncDirectory(sourceDir, targetDir, { dryRun });

  const globalSkillDir = PLATFORM_PATHS.antigravity.globalSkills;
  const sourceSkillDir = join(sourceDir, "skills", "model-dispatch-router");
  if (existsSync(sourceSkillDir)) {
    logger.info(`Installing Antigravity global skill to: ${globalSkillDir}`);
    syncDirectory(sourceSkillDir, globalSkillDir, { dryRun });
  }

  if (!dryRun) {
    logger.success("Antigravity plugin and global skill installation complete.");
  }
  return true;
}

export function update(sourceDir, options = {}) {
  if (!isInstalled()) {
    logger.warn("Antigravity plugin is not installed; skipping update (run install to initialize).");
    return false;
  }
  return install(sourceDir, options);
}

export function uninstall(options = {}) {
  const { dryRun = false } = options;
  const targetDir = PLATFORM_PATHS.antigravity.targetPlugin;
  if (existsSync(targetDir)) {
    if (dryRun) {
      logger.dryRun(`Would remove ${targetDir}`);
    } else {
      rmSync(targetDir, { recursive: true, force: true });
      logger.success(`Removed ${targetDir}`);
    }
  }
}
