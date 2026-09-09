#!/usr/bin/env node
'use strict';
// Temporary Git indexes preserve both the caller's staging area and task staging.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const runtimePath = file => /^(?:\.agent-logs|\.worktrees|\.agentmind)(?:\/|$)/.test(file);
function git(repo, args, options = {}) {
  return execFileSync('git', ['-C', repo, ...args], { maxBuffer: 128 * 1024 * 1024, ...options });
}
function fail(message, code = 13) { const error = new Error(message); error.code = code; throw error; }
function entries(manifest) {
  const lines = fs.readFileSync(manifest, 'utf8').split(/\r?\n/).filter(Boolean);
  if (!lines.length) fail('Missing or empty scope manifest');
  for (const line of lines) {
    if (line.includes('\\') || line.startsWith('/') || /^[A-Za-z]:/.test(line) || line.split('/').some(p => p === '.' || p === '..' || p === '.git') || line.includes('//')) fail(`Invalid scope: ${line}`);
  }
  return lines;
}
function allowed(file, scope) { return scope.some(p => file === p || (p.endsWith('/') && file.startsWith(p))); }
// --allow-extra: an orchestrator-supplied, explicitly-typed widening of scope
// for ONE diff/apply invocation — never something the dispatched agent can
// set itself (it has no access to this CLI). Same validation as a manifest
// line so a typo can't smuggle in '..' or an absolute path.
function parseExtra(csv) {
  if (!csv) return [];
  return csv.split(',').map(entry => entry.trim()).filter(Boolean).map(entry => {
    if (entry.includes('\\') || entry.startsWith('/') || /^[A-Za-z]:/.test(entry) || entry.split('/').some(p => p === '.' || p === '..' || p === '.git') || entry.includes('//')) fail(`Invalid --allow-extra entry: ${entry}`);
    return entry;
  });
}
function safeFile(repo, file) {
  if (!file || path.isAbsolute(file) || file.split('/').some(p => p === '..' || p.toLowerCase() === '.git')) fail(`Unsafe path: ${file}`);
  let cursor = repo;
  for (const part of file.split('/')) {
    cursor = path.join(cursor, part);
    try { if (fs.lstatSync(cursor).isSymbolicLink()) fail(`Symlink not supported: ${file}`); }
    catch (error) { if (error.code !== 'ENOENT' && error.code !== 'ENOTDIR') throw error; }
  }
  return cursor;
}
function treeEntries(repo, tree) {
  const result = new Map();
  for (const entry of git(repo, ['ls-tree', '-rz', tree]).toString().split('\0').filter(Boolean)) {
    const match = /^(\d+) (\S+) ([a-f0-9]+)\t([\s\S]*)$/.exec(entry);
    result.set(match[4], { mode: match[1], type: match[2], oid: match[3] });
  }
  return result;
}
function capture(repo, base, scope = null) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'dispatch-index-'));
  const env = { ...process.env, GIT_INDEX_FILE: path.join(temp, 'index') };
  try {
    git(repo, ['read-tree', base], { env });
    if (!scope) {
      // Include staged, unstaged, deleted and untracked files in ONE binary patch.
      git(repo, ['add', '-u', '--', '.'], { env });
      const untracked = git(repo, ['ls-files', '-z', '--others', '--exclude-standard'], { env }).toString().split('\0').filter(file => file && !runtimePath(file));
      if (untracked.length) git(repo, ['add', '--pathspec-from-file=-', '--pathspec-file-nul'], { env: { ...env, GIT_LITERAL_PATHSPECS: '1' }, input: untracked.join('\0') + '\0' });
    } else {
      const originals = treeEntries(repo, base);
      const files = new Set([...originals.keys(), ...git(repo, ['ls-files', '-z', '--cached', '--others', '--exclude-standard']).toString().split('\0').filter(Boolean)]);
      for (const file of files) {
        if (!allowed(file, scope)) continue;
        const absolute = safeFile(repo, file);
        let stat;
        try { stat = fs.statSync(absolute); } catch (error) { if (error.code !== 'ENOENT' && error.code !== 'ENOTDIR') throw error; }
        if (!stat) git(repo, ['update-index', '--force-remove', '--', file], { env });
        else {
          if (!stat.isFile()) fail(`Non-file snapshot target: ${file}`);
          const oid = git(repo, ['hash-object', '-w', '--path', file, '--', absolute]).toString().trim();
          const baseEntry = originals.get(file);
          const mode = process.platform === 'win32' ? (baseEntry?.mode || '100644') : (stat.mode & 0o111 ? '100755' : '100644');
          git(repo, ['update-index', '--add', '--cacheinfo', `${mode},${oid},${file}`], { env });
        }
      }
    }
    return git(repo, ['write-tree'], { env }).toString().trim();
  } finally { fs.rmSync(temp, { recursive: true, force: true }); }
}
function prepare(repo, worktree, manifest, baselineFile) {
  const scope = entries(manifest);
  if (scope.some(runtimePath)) fail('Runtime state cannot be snapshot scope');
  const head = git(worktree, ['rev-parse', 'HEAD']).toString().trim();
  if (git(worktree, ['status', '--porcelain']).toString().trim()) fail('Snapshot requires a clean new worktree');
  const base = treeEntries(repo, head);
  const tree = capture(repo, head, scope);
  const snapshot = treeEntries(repo, tree);
  for (const file of new Set([...base.keys(), ...snapshot.keys()])) {
    if (!allowed(file, scope)) continue;
    const target = safeFile(worktree, file);
    const item = snapshot.get(file);
    if (!item) { fs.rmSync(target, { force: true }); continue; }
    if (item.type !== 'blob' || item.mode === '120000') fail(`Unsupported snapshot entry: ${file}`);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    // checkout-index applies the repository's normal checkout filters (e.g. CRLF).
    fs.writeFileSync(target, git(repo, ['cat-file', '--filters', `--path=${file}`, item.oid]));
    if (process.platform !== 'win32') fs.chmodSync(target, item.mode === '100755' ? 0o755 : 0o644);
  }
  const actual = capture(worktree, head);
  if (actual !== tree) fail('Snapshot verification failed');
  const temporary = `${baselineFile}.${process.pid}.tmp`;
  // A real ref protects the baseline tree/blobs from git gc --prune, without a commit.
  const ref = `refs/agentmind/snapshots/${createHash('sha256').update(path.resolve(baselineFile)).digest('hex')}`;
  git(repo, ['update-ref', ref, tree]);
  fs.writeFileSync(temporary, JSON.stringify({ version: 1, tree, head, scope, ref }) + '\n');
  fs.renameSync(temporary, baselineFile);
  return tree;
}
function patch(repo, worktree, manifest, baselineFile, extra = []) {
  const scope = entries(manifest);
  const baseline = baselineFile && fs.existsSync(baselineFile) ? JSON.parse(fs.readFileSync(baselineFile, 'utf8')).tree : git(worktree, ['rev-parse', 'HEAD']).toString().trim();
  const current = capture(worktree, baseline);
  const changed = git(worktree, ['diff', '--no-renames', '--name-only', '-z', baseline, current]).toString().split('\0').filter(Boolean);
  const inScope = [];
  const outOfScope = [];
  for (const file of changed) {
    if (allowed(file, scope) || allowed(file, extra)) { safeFile(worktree, file); safeFile(repo, file); inScope.push(file); }
    else outOfScope.push(file);
  }
  // Out-of-scope files are reported, never silently included in the patch
  // data — a plain `diff` call surfaces them for review without needing
  // --allow-extra; only apply() below treats a nonempty outOfScope as fatal.
  const data = inScope.length ? git(worktree, ['diff', '--binary', '--full-index', '--no-renames', baseline, current, '--', ...inScope]) : Buffer.alloc(0);
  return { baseline, current, changed: inScope, outOfScope, data };
}
function apply(repo, worktree, manifest, baselineFile, extra = []) {
  const result = patch(repo, worktree, manifest, baselineFile, extra);
  if (result.outOfScope.length) fail(`scope_violation: ${result.outOfScope.join(', ')} — outside the task manifest. Re-run diff.sh/apply.sh with --allow-extra to explicitly include these paths, or update # FILES: and re-dispatch.`);
  const original = treeEntries(repo, result.baseline);
  for (const file of result.changed) {
    const target = safeFile(repo, file);
    const old = original.get(file);
    if (!old) { if (fs.existsSync(target)) fail(`New-file collision: ${file}`, 16); continue; }
    if (!fs.existsSync(target) || !fs.statSync(target).isFile()) fail(`Target changed since baseline: ${file}`, 16);
    const oid = git(repo, ['hash-object', '--path', file, '--', target]).toString().trim();
    const mode = process.platform === 'win32' ? old.mode : (fs.statSync(target).mode & 0o111 ? '100755' : '100644');
    if (oid !== old.oid || mode !== old.mode) fail(`Target changed since baseline: ${file}`, 16);
  }
  if (result.data.length) {
    git(repo, ['apply', '--check', '--binary', '-'], { input: result.data });
    git(repo, ['apply', '--binary', '-'], { input: result.data });
  }
  return result.changed;
}
module.exports = { prepare, patch, apply };
if (require.main === module) {
  const [command, repo, worktree, manifest, baselineFile, extraCsv] = process.argv.slice(2);
  try {
    if (command === 'prepare') console.log(prepare(repo, worktree, manifest, baselineFile));
    else if (command === 'diff') {
      const result = patch(repo, worktree, manifest, baselineFile, parseExtra(extraCsv));
      process.stdout.write(result.data);
      if (result.outOfScope.length) {
        console.error('\n== OUT OF SCOPE (not shown above; not applied without --allow-extra) ==');
        for (const file of result.outOfScope) console.error(file);
      }
    }
    else if (command === 'apply') console.log(`Applied ${apply(repo, worktree, manifest, baselineFile, parseExtra(extraCsv)).length} paths without staging.`);
    else fail('Usage: snapshot.js prepare|diff|apply REPO WORKTREE MANIFEST BASELINE [EXTRA_SCOPE_CSV]', 1);
  } catch (error) { console.error(error.message); process.exit(typeof error.code === 'number' ? error.code : 16); }
}
