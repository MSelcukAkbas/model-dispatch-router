#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const [role, repoRoot, skillRoot] = process.argv.slice(2);
const defaults = {
  backend:  { model: 'sonnet', effort: 'high',   readonly: false, bridge: true, maxBudgetUsd: 1.50 },
  design:   { model: 'sonnet', effort: 'high',   readonly: false, bridge: true, maxBudgetUsd: 2.00 },
  sdk:      { model: 'sonnet', effort: 'high',   readonly: false, bridge: true, maxBudgetUsd: 2.00 },
  general:  { model: 'sonnet', effort: 'medium', readonly: false, bridge: true, maxBudgetUsd: 1.00 },
  ops:      { model: 'sonnet', effort: 'high',   readonly: false, bridge: true, maxBudgetUsd: 2.00 },
  research: { model: 'haiku',  effort: 'low',    readonly: true,  bridge: true, maxBudgetUsd: 0.50 },
  judge:    { model: 'opus',   effort: 'high',   readonly: true,  bridge: true, maxBudgetUsd: 1.50 },
};

function fail(message) {
  process.stderr.write(`model-dispatch-route config error: ${message}\n`);
  process.exit(2);
}

let project = {};
const configPath = process.env.MODEL_DISPATCH_ROUTE_CONFIG || path.join(repoRoot, '.model-dispatch-route.json');
if (fs.existsSync(configPath)) {
  try { project = JSON.parse(fs.readFileSync(configPath, 'utf8')); }
  catch (error) { fail(`${configPath}: ${error.message}`); }
}

const configured = project.roles && project.roles[role];
if (!defaults[role] && !configured) fail(`unknown role '${role}'`);
const result = { ...(defaults[role] || {}), ...(configured || {}) };
if (!result.model || !['low', 'medium', 'high', 'xhigh', 'max'].includes(result.effort)) {
  fail(`role '${role}' has an invalid model or effort`);
}
if (typeof result.readonly !== 'boolean' || typeof result.bridge !== 'boolean') {
  fail(`role '${role}' readonly and bridge must be booleans`);
}
if (!(Number(result.maxBudgetUsd) > 0)) fail(`role '${role}' maxBudgetUsd must be positive`);

const persona = result.persona
  ? path.resolve(repoRoot, result.persona)
  : path.join(skillRoot, 'personas', `${role}.md`);
if (!fs.existsSync(persona)) fail(`persona not found: ${persona}`);

const opsMcpConfig = project.opsMcpConfig
  ? path.resolve(repoRoot, project.opsMcpConfig)
  : null;
if (opsMcpConfig && !fs.existsSync(opsMcpConfig)) fail(`ops MCP config not found: ${opsMcpConfig}`);

process.stdout.write(JSON.stringify({ ...result, persona, opsMcpConfig }));
