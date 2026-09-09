#!/usr/bin/env node
/** Standalone installer and synchronizer for Model Dispatch Router plugins.
 *
 * Discovers canonical local platform environments (Codex, Antigravity, Claude Code)
 * and installs or updates the plugins from plugins/<platform>/ directories.
 *
 * Platform-independent: works across Windows, macOS, and Linux without shell dependencies.
 *
 * Usage:
 *   node plugins/install.mjs
 *   node plugins/install.mjs --platform codex
 *   node plugins/install.mjs --sync
 *   node plugins/install.mjs --dry-run
 */
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { logger } from "./lib/logger.mjs";
import * as codexAdapter from "./platforms/codex.mjs";
import * as agyAdapter from "./platforms/antigravity.mjs";
import * as claudeAdapter from "./platforms/claude.mjs";

const pluginsRoot = import.meta.dirname;

const PLATFORMS = {
  codex: {
    adapter: codexAdapter,
    sourceDir: join(pluginsRoot, "codex", "agentmind-model-dispatch-router"),
  },
  antigravity: {
    adapter: agyAdapter,
    sourceDir: join(pluginsRoot, "antigravity", "agentmind-model-dispatch-router"),
  },
  claude: {
    adapter: claudeAdapter,
    sourceDir: join(pluginsRoot, "claude", "agentmind-model-dispatch-router"),
  },
};

export async function runInstall(options = {}) {
  const {
    targetPlatform = "all",
    syncOnly = false,
    dryRun = false,
  } = options;

  logger.step(syncOnly ? "AgentMind Plugin Sync" : "AgentMind Plugin Installation");
  if (dryRun) {
    logger.dryRun("Running in dry-run mode. No files will be modified.");
  }

  const selectedKeys = targetPlatform === "all"
    ? Object.keys(PLATFORMS)
    : [targetPlatform.toLowerCase()];

  for (const key of selectedKeys) {
    const entry = PLATFORMS[key];
    if (!entry) {
      logger.error(`Unknown platform '${key}'. Valid platforms: codex, antigravity, claude, all.`);
      continue;
    }

    const { adapter, sourceDir } = entry;
    logger.info(`Checking platform: ${adapter.displayName} (${adapter.name})...`);

    if (!existsSync(sourceDir)) {
      logger.error(`Source plugin directory not found: ${sourceDir}. Please run 'node plugins/build.mjs' first.`);
      continue;
    }

    const detected = adapter.detect();
    if (!detected) {
      logger.warn(`${adapter.displayName} is not detected on this machine. Skipping.`);
      continue;
    }

    const installed = adapter.isInstalled();
    if (syncOnly) {
      if (!installed) {
        logger.info(`${adapter.displayName} is not currently installed. Skipping (sync-only mode).`);
        continue;
      }
      logger.info(`Syncing updates for ${adapter.displayName}...`);
      adapter.update(sourceDir, { dryRun });
    } else {
      if (installed) {
        logger.info(`${adapter.displayName} plugin already exists. Updating...`);
        adapter.update(sourceDir, { dryRun });
      } else {
        logger.info(`Installing new plugin for ${adapter.displayName}...`);
        adapter.install(sourceDir, { dryRun });
      }
    }
  }

  logger.info("Done.");
}

// CLI argument parser
function parseArgs(args) {
  const options = {
    targetPlatform: "all",
    syncOnly: false,
    dryRun: false,
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--platform" && args[i + 1]) {
      options.targetPlatform = args[++i];
    } else if (arg === "--sync") {
      options.syncOnly = true;
    } else if (arg === "--dry-run") {
      options.dryRun = true;
    } else if (arg === "--help" || arg === "-h") {
      console.log(`
Usage: node plugins/install.mjs [options]

Options:
  --platform <codex|antigravity|claude|all>   Target platform (default: all)
  --sync                                      Only update previously installed platforms
  --dry-run                                   Preview actions without writing files
  --help, -h                                  Show this help message
      `);
      process.exit(0);
    }
  }
  return options;
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(import.meta.filename)) {
  const options = parseArgs(process.argv.slice(2));
  runInstall(options).catch((err) => {
    logger.error(`Install failed: ${err.message}`);
    process.exit(1);
  });
}
