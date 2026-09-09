#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const [source, logs, task] = process.argv.slice(2);
if (!source || !logs || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(task || '')) process.exit(1);
const parent = path.join(logs, 'runtimes', task);
fs.mkdirSync(parent, {recursive: true});
const target = path.join(parent, crypto.randomUUID());
fs.mkdirSync(target);
for (const folder of ['scripts', 'personas', 'mcp']) {
  fs.cpSync(path.join(source, folder), path.join(target, folder), {
    recursive: true,
    filter: p => !/(^|[\\/])(?:\.venv|__pycache__|\.pytest_cache|node_modules|\.git)(?:[\\/]|$)/.test(p)
      && !/(^|[\\/])accounts(?:\.local)?\.sh$/.test(p),
  });
}
fs.writeFileSync(path.join(target, 'runtime-manifest.json'), JSON.stringify({createdAt: new Date().toISOString(), task, source}, null, 2));
const pointer = path.join(logs, `${task}.runtime`);
fs.writeFileSync(pointer + '.tmp', target + '\n');
fs.renameSync(pointer + '.tmp', pointer);
console.log(target);
