#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
function file(dir, task, suffix) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(task) || task.includes('..')) throw new Error('Invalid task identifier');
  return path.join(dir, `${task}.${suffix}`);
}
function read(p) { try { return fs.readFileSync(p, 'utf8'); } catch { return ''; } }
function json(p) { try { return JSON.parse(read(p)); } catch { return null; } }
function atomic(p, value) {
  const temp = `${p}.${process.pid}.${crypto.randomUUID()}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
  fs.renameSync(temp, p);
}
function processIdentity(pid) {
  if (!Number.isSafeInteger(Number(pid)) || Number(pid) < 1) return null;
  try {
    if (process.platform !== 'win32') {
      const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
      const fields = stat.slice(stat.lastIndexOf(')') + 2).split(' ');
      if (fields[0] === 'Z') return null;
      return { kind: 'proc', pid: Number(pid), start: fields[19], boot: read('/proc/sys/kernel/random/boot_id').trim() };
    }
    // Resolve Git Bash PID to WINPID; never query a native process by MSYS PID.
    // `bash` can resolve to the Windows WSL shim outside Git Bash, so locate
    // the Bash shipped next to the Git executable first.
    let bash = 'bash';
    try {
      const git = execFileSync('where.exe', ['git'], { encoding: 'utf8', timeout: 5000, windowsHide: true })
        .split(/\r?\n/).map(x => x.trim()).find(Boolean);
      if (git) {
        const candidate = path.resolve(path.dirname(git), '..', 'bin', 'bash.exe');
        if (fs.existsSync(candidate)) bash = candidate;
      }
    } catch { /* portable fallback below */ }
    const lines = execFileSync(bash, ['-c', 'ps -p "$1" -l', '--', String(pid)], { encoding: 'utf8', timeout: 5000, windowsHide: true }).trim().split(/\r?\n/);
    const headers = lines[0].trim().split(/\s+/);
    const row = lines.slice(1).map(l => l.trim().replace(/^I\s+/, '').split(/\s+/)).find(r => r[headers.indexOf('PID')] === String(pid));
    const nativePid = Number(row?.[headers.indexOf('WINPID')]);
    if (!Number.isSafeInteger(nativePid) || nativePid < 1) return null;
    const start = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', `(Get-Process -Id ${nativePid} -ErrorAction Stop).StartTime.ToUniversalTime().Ticks`], { encoding: 'utf8', timeout: 5000, windowsHide: true }).trim();
    return start ? { kind: 'win32', pid: Number(pid), native_pid: nativePid, start } : null;
  } catch { return null; }
}
// codex's `--json` is JSONL like Claude's stream-json, but its event shape is
// its own (thread.started/turn.started/item.completed/turn.failed — verified
// live 2026-09-09 against codex-cli 0.152.1, both success and error paths),
// so it gets its own branch rather than forcing it through Claude's
// type:"result"/type:"assistant" shape. dispatch-codex.sh also asks codex for
// `-o/--output-last-message FILE` (written to `.codex.txt`) — the engine's
// own authoritative final text — preferred over reconstructing it from the
// JSONL when both are present.
function codexOutput(dir, task) {
  const raw = read(file(dir, task, 'codex.json'));
  const events = raw.split('\n').map(line => { try { return JSON.parse(line); } catch { return null; } }).filter(e => e && typeof e === 'object');
  const threadEvent = events.find(e => e.type === 'thread.started');
  const thread_id = (typeof threadEvent?.thread_id === 'string' && threadEvent.thread_id.trim()) ? threadEvent.thread_id.trim() : null;
  const terminal = events.findLast(e => e.type === 'turn.failed' || e.type === 'error') || null;
  const agentMessages = events.filter(e => e.type === 'item.completed' && e.item?.type === 'agent_message' && typeof e.item.text === 'string' && e.item.text.trim());
  const lastMessageFile = read(file(dir, task, 'codex.txt')).trim();
  const text = lastMessageFile || agentMessages.at(-1)?.item.text || '';
  const checkpoint = agentMessages.map(e => e.item.text).join('\n');
  return { terminal, text, checkpoint, thread_id, event_count: events.length };
}
function output(dir, task, engine) {
  if (engine === 'codex') return codexOutput(dir, task);
  const raw = read(file(dir, task, engine === 'agy' ? 'agy.json' : 'json'));
  let events = [];
  try { events = [JSON.parse(raw)]; } catch {
    for (const line of raw.split('\n')) { try { events.push(JSON.parse(line)); } catch { /* interrupted JSONL */ } }
  }
  events = events.filter(e => e && typeof e === 'object');
  const terminal = engine === 'agy' ? events.at(-1) : events.findLast(e => e.type === 'result');
  const text = engine === 'agy' ? terminal?.response : terminal?.result;
  const assistant = events.findLast(e => e.type === 'assistant' && Array.isArray(e.message?.content) && e.message.content.some(c => c.type === 'text' && typeof c.text === 'string' && c.text.trim()));
  const checkpoint = assistant?.message.content.filter(c => c.type === 'text').map(c => c.text).join('\n') || '';
  return { terminal, text: typeof text === 'string' ? text.trim() : '', checkpoint, event_count: events.length };
}
function engineFor(dir, task, run) {
  if (run?.engine) return run.engine;
  if (fs.existsSync(file(dir, task, 'codex.exitcode')) || fs.existsSync(file(dir, task, 'codex.meta'))) return 'codex';
  return fs.existsSync(file(dir, task, 'agy.exitcode')) || fs.existsSync(file(dir, task, 'agy.meta')) ? 'agy' : 'claude';
}
function classify(dir, task, rawExit, run) {
  const engine = engineFor(dir, task, run);
  const out = output(dir, task, engine), terminal = out.terminal;
  const bridge = json(file(dir, task, 'bridge.json'))?.result;
  const result = (status, exit_code, reason) => ({ status, exit_code, reason, engine, raw_exit_code: rawExit, result_available: !!out.text, checkpoint_available: !!out.checkpoint });
  if (rawExit === 124 || rawExit === 137) return result('timeout', 14, 'Engine interrupted by timeout or kill');
  if (terminal?.subtype === 'error_max_budget_usd' || (Array.isArray(terminal?.errors) && terminal.errors.some(e => /max(imum)?\s*budget|budget.*exceed/i.test(String(e))))) return result('budget_capped', 20, 'Per-task budget exhausted');
  if (terminal?.api_error_status === 429 || (terminal?.terminal_reason === 'api_error' && /session limit|usage limit|rate.?limit/i.test(String(terminal?.result)))) return result('quota_exhausted', 17, 'Provider quota exhausted');
  if (rawExit !== 0) {
    // codex reports its own errors as a JSONL event (type:"error" or
    // type:"turn.failed"), not on stderr — verified live 2026-09-09
    // (codex-cli 0.152.1) via a deliberately-invalid --model call: stderr
    // held only generic noise, the actual 400 was in the JSONL. Its
    // rate-limit/quota TEXT shape is not independently verified the same
    // way (would require actually exhausting quota) — this regex reuses the
    // same pattern the other two engines already match on, on a best-effort
    // basis, and falls through to a generic `failed` if it doesn't match.
    const errText = engine === 'codex' ? String(terminal?.error?.message || terminal?.message || '') : read(file(dir, task, engine === 'agy' ? 'agy.err' : 'err'));
    if (/usage limit|rate_limit_error|exceeded your.*(usage|quota)|\b429\b/i.test(errText)) return result('quota_exhausted', 17, 'Provider quota error');
    if (engine === 'codex' && errText) return result('failed', 1, `Engine reported an error: ${errText.slice(0, 200)}`);
    return result('failed', 1, 'Engine returned nonzero exit');
  }
  if (terminal?.is_error === true || (typeof terminal?.subtype === 'string' && terminal.subtype.startsWith('error'))) return result('failed', 1, 'Terminal event reports an error');
  if (fs.existsSync(file(dir, task, 'result-missing')) || !out.text) return result('result_missing', 21, 'RESULT_MISSING: no valid final response');
  if (run?.bridge_required && (!bridge || typeof bridge.summary !== 'string' || !bridge.summary.trim() || !['DONE', 'PARTIAL', 'BLOCKED'].includes(String(bridge.status).toUpperCase()))) return result('result_missing', 21, 'RESULT_MISSING: required structured Bridge result absent or invalid');
  const declared = String(bridge?.status || out.text.match(/^\s*STATUS\s*:\s*(DONE|PARTIAL|BLOCKED)\b/im)?.[1] || '').toUpperCase();
  if (declared === 'PARTIAL' || declared === 'BLOCKED') return result(declared.toLowerCase(), 22, 'Model reported incomplete work');
  return result('done', 0, 'Engine completed and result validated');
}
function begin(dir, task, engine, pid, bridgeRequired = false) {
  if (!['claude', 'agy', 'codex'].includes(engine)) throw new Error('Unsupported engine');
  fs.mkdirSync(dir, { recursive: true });
  const run = { schema_version: 1, run_id: crypto.randomUUID(), task, engine, pid: Number(pid), process_identity: processIdentity(pid), bridge_required: bridgeRequired, started_at: new Date().toISOString() };
  atomic(file(dir, task, 'run.json'), run);
  return run;
}
function finalize(dir, task, rawExit) {
  if (!Number.isInteger(rawExit) || rawExit < 0) throw new Error('Invalid engine exit code');
  const run = json(file(dir, task, 'run.json'));
  const result = { schema_version: 1, task, run_id: run?.run_id || null, ...classify(dir, task, rawExit, run), completed_at: new Date().toISOString(), hook: { status: 'pending' } };
  const out = output(dir, task, result.engine);
  if (result.engine === 'codex' && out.thread_id) {
    result.thread_id = out.thread_id;
    const metaPath = file(dir, task, 'codex.meta');
    try {
      if (fs.existsSync(metaPath)) {
        let metaContent = read(metaPath);
        if (/^thread_id=/m.test(metaContent)) {
          metaContent = metaContent.replace(/^thread_id=.*$/m, `thread_id=${out.thread_id}`);
        } else {
          metaContent = `${metaContent.trimEnd()}\nthread_id=${out.thread_id}\n`;
        }
        fs.writeFileSync(metaPath, metaContent);
      }
    } catch { /* fail-soft */ }
  }
  // Publish before optional session-end hooks and compatibility exit markers.
  atomic(file(dir, task, 'final-status.json'), result);
  if (result.exit_code !== 0) atomic(file(dir, task, 'checkpoint.json'), { run_id: result.run_id, status: result.status, summary: out.checkpoint || out.text || 'No assistant text captured before interruption.', event_count: out.event_count, captured_at: new Date().toISOString() });
  return result;
}
function status(dir, task) {
  const run = json(file(dir, task, 'run.json')), final = json(file(dir, task, 'final-status.json'));
  if (final && (!run || final.run_id === run.run_id) && Number.isInteger(final.exit_code)) {
    if (final.hook?.status === 'pending') {
      if (Date.now() - Date.parse(final.completed_at) < 60000) return { ...final, engine_status: final.status, status: 'finalizing', exit_code: 10, reason: 'Engine result retained; session-end hook pending' };
      return { ...final, engine_status: final.status, status: 'hook_incomplete', exit_code: final.exit_code || 24, reason: 'Engine result retained; session-end hook did not close within 60s' };
    }
    if (final.hook?.status === 'failed' && final.exit_code === 0) return { ...final, engine_status: final.status, status: 'hook_failed', exit_code: 24, reason: 'Engine result retained; session-end hook failed' };
    return final;
  }
  const engine = engineFor(dir, task, run);
  const exitSuffix = engine === 'agy' ? 'agy.exitcode' : engine === 'codex' ? 'codex.exitcode' : 'exitcode';
  const exitPath = file(dir, task, exitSuffix);
  if (fs.existsSync(exitPath)) {
    const raw = read(exitPath).trim();
    if (!/^\d+$/.test(raw)) return { status: 'failed', exit_code: 1, reason: 'Invalid exit marker' };
    return classify(dir, task, Number(raw), run);
  }
  if (run) {
    const current = processIdentity(run.pid);
    if (current && run.process_identity && JSON.stringify(current) === JSON.stringify(run.process_identity)) return { status: 'running', exit_code: 10, pid: run.pid };
    return { status: 'orphaned', exit_code: 23, reason: 'Runner identity missing, gone, or changed; inspect captured output' };
  }
  if (fs.existsSync(file(dir, task, 'pid')) || fs.existsSync(file(dir, task, 'agy.pid')) || fs.existsSync(file(dir, task, 'codex.pid'))) return { status: 'orphaned', exit_code: 23, reason: 'Legacy PID cannot establish process ownership; inspect task manually' };
  return { status: 'not_found', exit_code: 11, reason: 'No dispatch record' };
}
function hook(dir, task, hookExit) {
  if (!Number.isInteger(hookExit) || hookExit < 0) throw new Error('Invalid hook exit code');
  const final = json(file(dir, task, 'final-status.json')), run = json(file(dir, task, 'run.json'));
  if (!final || (run && final.run_id !== run.run_id)) throw new Error('No current finalized engine result');
  final.hook = { status: hookExit === 0 ? 'done' : 'failed', exit_code: hookExit, completed_at: new Date().toISOString() };
  atomic(file(dir, task, 'final-status.json'), final);
  return final;
}
function collect(dir, task) {
  const state = status(dir, task), run = json(file(dir, task, 'run.json'));
  const out = output(dir, task, engineFor(dir, task, run));
  const lines = [`== report (${task}) ==`, `${state.status}: ${state.reason || ''}`];
  if (out.text) lines.push(out.text);
  if (state.exit_code !== 0 && out.checkpoint) lines.push('PARTIAL CHECKPOINT — captured assistant text, not verified completion:', out.checkpoint);
  if (!out.text && !out.checkpoint) lines.push('(No recoverable assistant text.)');
  if (out.terminal?.total_cost_usd != null) lines.push(`Cost: $${out.terminal.total_cost_usd}; turns: ${out.terminal.num_turns ?? '?'}`);
  return { ...state, report: lines.join('\n') };
}
function main(args) {
  const [command, dir, task, ...rest] = args;
  if (!dir || !task) throw new Error('Usage: lifecycle.js begin|finalize|hook|status|collect LOG_DIR TASK [ARGS]');
  let value;
  if (command === 'begin') value = begin(dir, task, rest[0], rest[1], ['true', '1', 'bridge-required'].includes(rest[2]));
  else if (command === 'finalize') value = finalize(dir, task, Number(rest[0]));
  else if (command === 'hook') value = hook(dir, task, Number(rest[0]));
  else if (command === 'status') value = status(dir, task);
  else if (command === 'collect') value = collect(dir, task);
  else throw new Error('Unknown lifecycle command');
  console.log(command === 'collect' ? value.report : command === 'status' ? `${value.status}: task=${task}${value.reason ? ' — ' + value.reason : ''}` : JSON.stringify(value));
  return ['begin', 'hook'].includes(command) ? 0 : value.exit_code;
}
if (require.main === module) { try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(`lifecycle_error: ${e.message}`); process.exitCode = 1; } }
module.exports = { begin, finalize, hook, status, collect, processIdentity };
