#!/usr/bin/env node
'use strict';
// Fills the structural gap both non-Claude dispatch engines share: neither
// agy nor codex has a per-invocation MCP config, so their FINDINGS: block
// (personas/agy-*.md, personas/codex-*.md) never reaches knowledge_write the
// way Claude's submit_result.findings[] does automatically — confirmed by
// `am coverage` showing 0 claims for every agy dispatch before this existed
// (2026-09-09). This script closes that gap directly against
// knowledge-store.js's insertKnowledge() (the same function agent-bridge.js's
// writeFindings/toolKnowledgeWrite call), no MCP/HTTP roundtrip needed since
// this always runs as a local post-process step in the same repo checkout.
//
// Never throws past main(): the calling dispatch script runs this AFTER the
// engine has already finished and reported its own exit code — a
// knowledge-store bug must not turn an otherwise-successful dispatch into a
// failed one.
//
// Usage: ingest-findings.js LOG_DIR TASK ENGINE(agy|codex)
const fs = require('node:fs');
const path = require('node:path');
const { extractFindingsLines, parseLine, parseEvidence } = require('./findings-parser');

const [, , logDir, task, engine] = process.argv;
if (!logDir || !task || !['agy', 'codex'].includes(engine)) {
  console.error('usage: ingest-findings.js LOG_DIR TASK agy|codex');
  process.exit(1);
}

function readRole(metaPath) {
  try {
    const match = fs.readFileSync(metaPath, 'utf8').match(/^role=(.*)$/m);
    return match ? match[1].trim() : '';
  } catch {
    return '';
  }
}

// agy wraps its whole reply in one JSON object's `.response` field; codex
// writes its final message straight to a plain text file via
// `-o/--output-last-message` (simpler — no JSON unwrap needed).
function readResponseText(logDir, task, engine) {
  if (engine === 'codex') {
    try { return fs.readFileSync(path.join(logDir, `${task}.codex.txt`), 'utf8'); }
    catch (error) { throw new Error(`cannot read ${task}.codex.txt: ${error.message}`); }
  }
  const jsonPath = path.join(logDir, `${task}.agy.json`);
  try { return JSON.parse(fs.readFileSync(jsonPath, 'utf8')).response; }
  catch (error) { throw new Error(`cannot read/parse ${jsonPath}: ${error.message}`); }
}

async function main() {
  const prefix = `ingest-findings(${engine})`;
  let response;
  try {
    response = readResponseText(logDir, task, engine);
  } catch (error) {
    console.error(`${prefix}: ${error.message}`);
    return;
  }
  if (typeof response !== 'string' || !response.trim()) {
    console.log(`${prefix}: no response text — nothing to ingest.`);
    return;
  }

  const lines = extractFindingsLines(response);
  if (lines === null) {
    console.log(`${prefix}: no FINDINGS: block found — nothing to ingest.`);
    return;
  }
  if (lines.length === 0) {
    console.log(`${prefix}: FINDINGS: none — nothing to ingest.`);
    return;
  }

  const role = readRole(path.join(logDir, `${task}.${engine}.meta`));
  const cwd = process.env.DISPATCH_REPO_ROOT || process.cwd();
  const { insertKnowledge, CATEGORIES } = require(path.join(__dirname, '..', 'mcp', 'bridge', 'knowledge-store.js'));

  let written = 0, skipped = 0;
  for (const line of lines) {
    const f = parseLine(line);
    if (!f.topic || !f.category || !f.claim) {
      console.error(`${prefix}: skipping malformed line (missing topic/category/claim): ${line}`);
      skipped++;
      continue;
    }
    if (!CATEGORIES.includes(f.category)) {
      console.error(`${prefix}: skipping line with invalid category '${f.category}' (must be one of ${CATEGORIES.join('|')}): ${line}`);
      skipped++;
      continue;
    }
    try {
      insertKnowledge({
        topic: f.topic,
        category: f.category,
        claim: f.claim,
        evidence: parseEvidence(f.evidence),
        scope: f.scope === 'incidental' ? 'incidental' : 'task',
        source_task: task,
        source_role: role || engine,
      }, cwd);
      written++;
    } catch (error) {
      console.error(`${prefix}: failed to write finding (${line}): ${error.message}`);
      skipped++;
    }
  }
  console.log(`${prefix}: ${written} finding(s) written, ${skipped} skipped.`);
  if (written > 0) {
    trySyncAgentMind(cwd, prefix);
  }
}

function trySyncAgentMind(cwd, prefix) {
  const { spawnSync } = require('node:child_process');
  try {
    const res = spawnSync('am', ['sync', cwd], {
      stdio: 'pipe',
      encoding: 'utf8',
      timeout: 10000,
    });
    if (res.status === 0) {
      const firstLine = res.stdout ? res.stdout.trim().split('\n')[0] : 'ok';
      console.log(`${prefix}: AgentMind synchronized (${firstLine}).`);
      return;
    }
  } catch {
    // am not in PATH, try local fallback
  }

  const agentmindDir = path.join(__dirname, '..', 'mcp', 'agentmind');
  if (fs.existsSync(path.join(agentmindDir, 'pyproject.toml'))) {
    try {
      const res = spawnSync('uv', ['run', 'am', 'sync', cwd], {
        cwd: agentmindDir,
        stdio: 'pipe',
        encoding: 'utf8',
        timeout: 15000,
      });
      if (res.status === 0) {
        console.log(`${prefix}: AgentMind synchronized via uv.`);
      }
    } catch {
      // Fail-open: AgentMind is an enhancement, missing tooling must not fail dispatch
    }
  }
}

main().catch(error => console.error(`ingest-findings: unexpected failure (ignored): ${error.message}`));
