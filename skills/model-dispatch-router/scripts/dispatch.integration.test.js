#!/usr/bin/env node
'use strict';
// Hermetic CLI integration: all model and quota executables are fixture doubles.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

function discoverBash() {
  if (process.env.DISPATCH_TEST_BASH) return process.env.DISPATCH_TEST_BASH;
  if (process.platform !== 'win32') return '/bin/bash';
  const git = spawnSync('where.exe', ['git'], {encoding: 'utf8'}).stdout || '';
  for (const executable of git.trim().split(/\r?\n/)) {
    const candidate = path.resolve(path.dirname(executable), '../bin/bash.exe');
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}
const bash = discoverBash();
const posix = value => value.replace(/\\/g, '/');
const quote = value => "'" + value.replace(/'/g, "'\\''") + "'";

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dispatch-integration-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const repo = path.join(root, 'repo');
  const skill = path.join(root, 'plugin');
  const bin = path.join(root, 'bin');
  fs.mkdirSync(repo); fs.mkdirSync(bin);
  for (const folder of ['scripts', 'personas', 'mcp']) {
    fs.cpSync(path.join(__dirname, '..', folder), path.join(skill, folder), {
      recursive: true,
      filter: p => !/(^|[\\/])(?:\.venv|__pycache__|\.pytest_cache|node_modules|accounts(?:\.local)?\.sh)(?:[\\/]|$)/.test(p),
    });
  }
  fs.writeFileSync(path.join(skill, 'scripts', 'usage.sh'), '#!/bin/bash\nexit 1\n');
  fs.writeFileSync(path.join(bin, 'agy'), '#!/bin/bash\nprintf "%s\\n" "$FAKE_RESPONSE"\nexit "${FAKE_EXIT:-0}"\n', {mode: 0o755});
  fs.writeFileSync(path.join(bin, 'claude'), '#!/bin/bash\nprintf "%s\\n" "$FAKE_RESPONSE"\nexit "${FAKE_EXIT:-0}"\n', {mode: 0o755});
  fs.writeFileSync(path.join(repo, 'prompt.md'), '# GOAL: Verify fixture delivery\nRead the fixture.\n');
  fs.writeFileSync(path.join(repo, '.model-dispatch-router.json'), JSON.stringify({roles: {research: {bridge: false}}}));
  const env = {...process.env, AGENTMIND_DISABLE: '1', CLAUDE_CONFIG_DIR: posix(path.join(root, 'claude-config')), AGY_BIN: posix(path.join(bin, 'agy')), CLAUDE_BIN: posix(path.join(bin, 'claude'))};
  delete env.DISPATCH_PINNED_TASK;
  delete env.MODEL_DISPATCH_ROUTE_CONFIG;
  function run(script, args = [], extra = {}) {
    const command = `export PATH=${quote(posix(bin))}:$PATH\nbash ${quote(posix(script))} ${args.map(a => quote(String(a))).join(' ')}`;
    return spawnSync(bash, ['-c', command], {cwd: repo, env: {...env, ...extra}, encoding: 'utf8', timeout: 45000});
  }
  const initialized = spawnSync('git', ['init', '-q', repo], {encoding: 'utf8'});
  assert.equal(initialized.status, 0, initialized.stderr);
  return {repo, skill, run, logs: path.join(repo, '.agent-logs')};
}

for (const scenario of [
  {name: 'empty AGY output cannot succeed', task: 'EMPTY', response: '', code: 21},
  {name: 'empty AGY response cannot succeed', task: 'BLANK', response: '{"response":"  "}', code: 21},
  {name: 'valid AGY response is delivered', task: 'VALID', response: '{"response":"STATUS: DONE\\nVerified fixture."}', code: 0},
]) {
  test(scenario.name, {skip: !bash}, t => {
    const f = fixture(t);
    const dispatched = f.run(path.join(f.skill, 'scripts/dispatch-agy.sh'), ['research', scenario.task, 'prompt.md', '1'], {FAKE_RESPONSE: scenario.response});
    const raw = fs.existsSync(path.join(f.logs, `${scenario.task}.agy.json`))
      ? fs.readFileSync(path.join(f.logs, `${scenario.task}.agy.json`), 'utf8') : '<missing>';
    assert.equal(dispatched.status, scenario.code, dispatched.stdout + dispatched.stderr + `\nraw=${JSON.stringify(raw)}`);
    assert.ok(fs.existsSync(path.join(f.logs, `${scenario.task}.final-status.json`)));
    // Remove the original plugin source: the runtime's recovery launcher must work.
    const runtime = fs.readFileSync(path.join(f.logs, `${scenario.task}.runtime`), 'utf8').trim();
    fs.renameSync(f.skill, f.skill + '.retired');
    const status = f.run(path.join(runtime, 'scripts/task.sh'), ['status', scenario.task]);
    assert.equal(status.status, scenario.code, status.stdout + status.stderr);
    const collected = f.run(path.join(runtime, 'scripts/task.sh'), ['collect', scenario.task]);
    assert.equal(collected.status, scenario.code, collected.stdout + collected.stderr);
    if (scenario.code === 0) assert.match(collected.stdout, /Verified fixture/);
  });
}

test('Claude bridge-disabled delivery survives unavailable quota query', {skip: !bash}, async t => {
  const f = fixture(t);
  const result = f.run(path.join(f.skill, 'scripts/dispatch.sh'), ['research', 'CLAUDE', 'prompt.md', '--timeout', '1'], {
    FAKE_RESPONSE: JSON.stringify({type: 'result', subtype: 'success', result: 'STATUS: DONE\nVerified Claude fixture.', is_error: false}),
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  const final = path.join(f.logs, 'CLAUDE.final-status.json');
  const deadline = Date.now() + 15000;
  while (!fs.existsSync(final) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 100));
  assert.ok(fs.existsSync(final), result.stdout + result.stderr);
  const collected = f.run(path.join(f.skill, 'scripts/task.sh'), ['collect', 'CLAUDE']);
  assert.equal(collected.status, 0, collected.stdout + collected.stderr);
  assert.match(collected.stdout, /Verified Claude fixture/);
});
