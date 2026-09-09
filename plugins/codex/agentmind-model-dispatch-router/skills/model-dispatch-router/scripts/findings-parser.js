'use strict';
// Shared FINDINGS: block parser — the pipe-delimited shape every dispatch
// engine's read-only/coder personas end their response with (agy-research.md,
// agy-judge.md, agy-coder.md, codex-research.md, codex-judge.md,
// codex-coder.md). One parser, one place to fix if the shape ever changes.

// Returns the trimmed, non-empty lines inside a `FINDINGS:` block, or null if
// no such block exists. An explicit literal "none" line means "checked,
// nothing durable" and is returned as an empty array, not null — callers
// should treat null and [] differently only if they care about "block
// absent" vs "block present but empty".
function extractFindingsLines(text) {
  if (typeof text !== 'string') return null;
  const block = text.match(/^FINDINGS:\s*\n([\s\S]*?)(?:\n[A-Z_]+:|$)/m);
  if (!block) return null;
  const lines = block[1].split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length === 1 && lines[0].toLowerCase() === 'none') return [];
  return lines;
}

// `topic=x | category=y | claim=z | evidence=a:1, b:2 | scope=task` -> object.
// Missing required fields are the caller's problem to reject, not this
// function's — a malformed line is still a valid parse result (empty-ish
// object), just not a usable one.
function parseLine(line) {
  const fields = {};
  for (const part of line.split('|')) {
    const eq = part.indexOf('=');
    if (eq === -1) continue;
    fields[part.slice(0, eq).trim()] = part.slice(eq + 1).trim();
  }
  return fields;
}

function parseEvidence(raw) {
  return (raw || '')
    .split(',')
    .map(entry => entry.trim())
    .filter(Boolean)
    .map(entry => {
      const colon = entry.lastIndexOf(':');
      if (colon === -1) return { file: entry, line: null };
      const line = Number(entry.slice(colon + 1));
      return { file: entry.slice(0, colon), line: Number.isFinite(line) ? line : null };
    });
}

module.exports = { extractFindingsLines, parseLine, parseEvidence };
