import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { logger } from "./logger.mjs";

export function syncDirectory(source, target, options = {}) {
  const { dryRun = false, clean = true, filter = null } = options;

  if (dryRun) {
    logger.dryRun(`Would copy '${source}' -> '${target}' (clean=${clean})`);
    return true;
  }

  if (clean && existsSync(target)) {
    try {
      rmSync(target, { recursive: true, force: true });
    } catch {
      // Graceful fallback for Windows file locks: let cpSync overwrite in-place
    }
  }

  mkdirSync(target, { recursive: true });
  cpSync(source, target, {
    recursive: true,
    filter: filter || undefined,
  });

  return true;
}
