'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { prepare, patch, apply } = require('../snapshot');

function setup(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'snapshot-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const repo = path.join(root, 'repo'), wt = path.join(root, 'wt');
  fs.mkdirSync(repo);
  const git = (...args) => execFileSync('git', ['-C', repo, ...args], { stdio: ['pipe', 'pipe', 'pipe'] }).toString();
  const write = (where, file, data) => {
    fs.mkdirSync(path.dirname(path.join(where, file)), { recursive: true });
    fs.writeFileSync(path.join(where, file), data);
  };
  git('init');
  git('config', 'user.email', 'test@example.invalid');
  git('config', 'user.name', 'Snapshot Test');
  git('config', 'core.autocrlf', 'false');
  write(repo, 'src/a.txt', 'initial\n');
  write(repo, 'src/delete.txt', 'delete\n');
  write(repo, 'other.txt', 'other\n');
  git('add', '.');
  git('commit', '-qm', 'fixture');
  git('worktree', 'add', '--detach', wt);
  const manifest = path.join(root, 'scope'), baseline = path.join(root, 'snapshot.json');
  fs.writeFileSync(manifest, 'src/\n');
  return { repo, wt, git, write, manifest, baseline };
}

test('dirty scoped snapshot preserves index and applies only task delta including binary/new/deletion', t => {
  const c = setup(t);
  c.write(c.repo, 'src/a.txt', 'staged\n');
  c.git('add', 'src/a.txt');
  c.write(c.repo, 'src/a.txt', 'dirty input\n');
  c.write(c.repo, 'src/input.bin', Buffer.from([0, 1, 2, 255]));
  c.write(c.repo, 'other.txt', 'outside dirty scope\n');
  fs.unlinkSync(path.join(c.repo, 'src/delete.txt'));
  const staged = c.git('diff', '--cached');
  prepare(c.repo, c.wt, c.manifest, c.baseline);
  assert.equal(fs.readFileSync(path.join(c.wt, 'src/a.txt'), 'utf8'), 'dirty input\n');
  assert.equal(fs.readFileSync(path.join(c.wt, 'other.txt'), 'utf8'), 'other\n');
  assert.equal(fs.existsSync(path.join(c.wt, 'src/delete.txt')), false);
  assert.equal(patch(c.repo, c.wt, c.manifest, c.baseline).data.length, 0);
  c.write(c.wt, 'src/a.txt', 'task result\n');
  c.write(c.wt, 'src/new name.bin', Buffer.from([0, 5, 6, 255]));
  execFileSync('git', ['-C', c.wt, 'add', 'src/a.txt', 'src/new name.bin']);
  fs.unlinkSync(path.join(c.wt, 'src/input.bin'));
  apply(c.repo, c.wt, c.manifest, c.baseline);
  assert.equal(c.git('diff', '--cached'), staged);
  assert.equal(fs.readFileSync(path.join(c.repo, 'src/a.txt'), 'utf8'), 'task result\n');
  assert.deepEqual(fs.readFileSync(path.join(c.repo, 'src/new name.bin')), Buffer.from([0, 5, 6, 255]));
  assert.equal(fs.existsSync(path.join(c.repo, 'src/input.bin')), false);
  assert.equal(fs.readFileSync(path.join(c.repo, 'other.txt'), 'utf8'), 'outside dirty scope\n');
});

test('new-file collision blocks ALL tracked writes before apply', t => {
  const c = setup(t);
  c.write(c.wt, 'src/a.txt', 'task\n');
  c.write(c.wt, 'src/new.txt', 'task new\n');
  c.write(c.repo, 'src/new.txt', 'user file\n');
  assert.throws(() => apply(c.repo, c.wt, c.manifest, c.baseline), /collision/);
  assert.equal(fs.readFileSync(path.join(c.repo, 'src/a.txt'), 'utf8'), 'initial\n');
  assert.equal(fs.readFileSync(path.join(c.repo, 'src/new.txt'), 'utf8'), 'user file\n');
});

test('target drift outside changed hunks still blocks application', t => {
  const c = setup(t);
  prepare(c.repo, c.wt, c.manifest, c.baseline);
  c.write(c.wt, 'src/a.txt', 'task\n');
  c.write(c.repo, 'src/a.txt', 'concurrent edit\n');
  assert.throws(() => apply(c.repo, c.wt, c.manifest, c.baseline), /Target changed/);
  assert.equal(fs.readFileSync(path.join(c.repo, 'src/a.txt'), 'utf8'), 'concurrent edit\n');
});

test('staged out-of-scope edit is rejected on apply and isolated in diff', t => {
  const c = setup(t);
  c.write(c.wt, 'other.txt', 'bad\n');
  execFileSync('git', ['-C', c.wt, 'add', 'other.txt']);
  const res = patch(c.repo, c.wt, c.manifest, c.baseline);
  assert.deepEqual(res.outOfScope, ['other.txt']);
  assert.equal(res.data.length, 0);
  assert.throws(() => apply(c.repo, c.wt, c.manifest, c.baseline), /scope_violation/);
});

test('missing scope and path traversal are rejected', t => {
  const c = setup(t);
  fs.writeFileSync(c.manifest, '');
  assert.throws(() => prepare(c.repo, c.wt, c.manifest, c.baseline), /empty scope/);
  fs.writeFileSync(c.manifest, '../escape\n');
  assert.throws(() => prepare(c.repo, c.wt, c.manifest, c.baseline), /Invalid scope/);
});

test('snapshot baseline survives prune and runtime files are never task patch inputs', t => {
  const c = setup(t);
  c.write(c.repo, 'src/a.txt', 'dirty baseline\n');
  prepare(c.repo, c.wt, c.manifest, c.baseline);
  const metadata = JSON.parse(fs.readFileSync(c.baseline, 'utf8'));
  assert.equal(c.git('rev-parse', metadata.ref).trim(), metadata.tree);
  c.git('prune', '--expire', 'now');
  c.write(c.wt, '.agent-logs/task.log', 'runtime\n');
  c.write(c.wt, '.agentmind/store', 'runtime\n');
  c.write(c.wt, '.worktrees/nested/file', 'runtime\n');
  assert.equal(patch(c.repo, c.wt, c.manifest, c.baseline).data.length, 0);
  c.write(c.wt, 'src/a.txt', 'after prune\n');
  apply(c.repo, c.wt, c.manifest, c.baseline);
  assert.equal(fs.readFileSync(path.join(c.repo, 'src/a.txt'), 'utf8'), 'after prune\n');
});
