#!/usr/bin/env node
'use strict';
// PostToolUse checkpoint persistence. No model call or price-table guess required.
const fs = require('node:fs');
const path = require('node:path');
function checkpoint(input, env = process.env) {
  const task = env.DISPATCH_TASK_ID;
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(task || '') || !env.DISPATCH_REPO_ROOT) return null;
  const logs = path.join(env.DISPATCH_REPO_ROOT, '.agent-logs');
  const read = file => { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return {}; } };
  const run = read(path.join(logs, `${task}.run.json`));
  const file = path.join(logs, `${task}.checkpoint.json`);
  const previous = read(file);
  let text = '';
  if (input.transcript_path) {
    let fd;
    try {
      fd = fs.openSync(input.transcript_path, 'r');
      const size = fs.fstatSync(fd).size;
      const buffer = Buffer.alloc(Math.min(size, 1024 * 1024));
      fs.readSync(fd, buffer, 0, buffer.length, Math.max(0, size - buffer.length));
      for (const line of buffer.toString('utf8').split('\n')) {
        try {
          const event = JSON.parse(line);
          if (event.type !== 'assistant') continue;
          const content = event.message?.content;
          if (Array.isArray(content)) {
            const value = content.filter(c => c.type === 'text').map(c => c.text).join('\n').trim();
            if (value) text = value.slice(-12000);
          }
        } catch { /* incomplete tail line */ }
      }
    } finally { if (fd !== undefined) fs.closeSync(fd); }
  }
  const count = (previous.toolCount || 0) + 1;
  const start = Number(env.DISPATCH_STARTED_MS || Date.now());
  const duration = Number(env.DISPATCH_TIMEOUT_MIN || 25) * 60000;
  const nearDeadline = Date.now() - start >= duration * 0.85;
  const record = { runId: run.runId || null, updatedAt: new Date().toISOString(), toolCount: count,
    source: 'post-tool-hook', lastTool: String(input.tool_name || ''), summary: text || previous.summary || '',
    partial: true, nearDeadline };
  fs.mkdirSync(logs, {recursive: true});
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(record, null, 2) + '\n');
  fs.renameSync(temporary, file);
  if (count % 5 === 0 || (nearDeadline && !previous.nearDeadline)) {
    return { hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext:
      (nearDeadline ? '85% of the time allowance has elapsed. ' : '') +
      'Write a concise CHECKPOINT now: findings, changed paths, completed checks and remaining work. If you cannot finish within the remaining allowance, submit a PARTIAL result with these details. Do not claim completion for unverified work.' } };
  }
  return null;
}
if (require.main === module) {
  let data = '';
  process.stdin.on('data', chunk => { if (data.length < 2 * 1024 * 1024) data += chunk; });
  process.stdin.on('end', () => {
    try { const result = checkpoint(JSON.parse(data || '{}')); if (result) console.log(JSON.stringify(result)); }
    catch (error) { console.error(`checkpoint warning: ${error.message}`); }
  });
}
module.exports = { checkpoint };
