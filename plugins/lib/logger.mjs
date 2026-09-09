/** Simple console logger for plugins build and install workflows. */

export const logger = {
  info(msg) {
    console.log(`[INFO] ${msg}`);
  },
  success(msg) {
    console.log(`\x1b[32m[SUCCESS]\x1b[0m ${msg}`);
  },
  warn(msg) {
    console.log(`\x1b[33m[WARN]\x1b[0m ${msg}`);
  },
  error(msg) {
    console.error(`\x1b[31m[ERROR]\x1b[0m ${msg}`);
  },
  dryRun(msg) {
    console.log(`\x1b[36m[DRY-RUN]\x1b[0m ${msg}`);
  },
  step(name) {
    console.log(`\n\x1b[1m=== ${name} ===\x1b[0m`);
  }
};
