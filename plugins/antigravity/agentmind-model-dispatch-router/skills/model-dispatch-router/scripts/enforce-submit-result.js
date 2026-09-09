#!/usr/bin/env node
// Stop hook — dispatch edilen alt modelin turu bitirmeden önce agent-bridge
// submit_result tool'unu ÇAĞIRMIŞ olmasını zorunlu kılar. dispatch.sh bunu
// SADECE writer rollere (bridge erişimi olan) --settings ile geçer, env
// DISPATCH_TASK_ID zaten dispatch.sh'ın subshell'inde export edilmiş olur.
//
// Sözleşme (Claude Code Stop hook): exit 0 = durabilir. exit 2 = durma
// engellenir, stderr metni modele "devam et" talimatı olarak geri beslenir.
// Sonsuz döngü freni: MAX_BLOCKS denemeden sonra pes edip durmaya izin
// verir + result-missing işareti bırakır (budget-clamp'taki aynı disiplin).
'use strict';
const fs = require('fs');
const path = require('path');

const REPO_ROOT = process.env.DISPATCH_REPO_ROOT
  ? path.resolve(process.env.DISPATCH_REPO_ROOT)
  : process.cwd();
const LOG_DIR = path.join(REPO_ROOT, '.agent-logs');
const MAX_BLOCKS = 3;

const taskId = process.env.DISPATCH_TASK_ID;
if (!taskId) {
  // Bridge bağlamı yok (bu hook yanlışlıkla başka bir oturuma karışmış
  // olabilir) — no-op, asla bilmediği bir oturumu bloke etme.
  process.exit(0);
}

const bridgePath = path.join(LOG_DIR, `${taskId}.bridge.json`);
const countPath = path.join(LOG_DIR, `${taskId}.stophook-count`);
const missingMarker = path.join(LOG_DIR, `${taskId}.result-missing`);

let hasResult = false;
try {
  const state = JSON.parse(fs.readFileSync(bridgePath, 'utf8'));
  hasResult = !!state.result;
} catch {
  // dosya yok/henüz oluşmamış/bozuk — submit edilmemiş say
}

if (hasResult) {
  process.exit(0);
}

let count = 0;
try { count = parseInt(fs.readFileSync(countPath, 'utf8'), 10) || 0; } catch { /* ilk deneme */ }
count += 1;
fs.writeFileSync(countPath, String(count));

if (count > MAX_BLOCKS) {
  fs.writeFileSync(
    missingMarker,
    `submit_result hiç çağrılmadı — ${count - 1} blok denemesinden sonra pes edildi (${new Date().toISOString()}). collect.sh'taki serbest-metin son mesaja güven, yapılandırılmış sonuç yok.`
  );
  process.exit(0); // insan/orkestratör devreye girsin, sonsuz döngü yok
}

const reason =
  `Görevi bitirmeden önce agent-bridge MCP tool'undan submit_result çağırman ZORUNLU ` +
  `(status, summary, opsiyonel changed_files/risk/verified). Henüz çağırmadın ` +
  `(deneme ${count}/${MAX_BLOCKS}). Şimdi çağır, sonra dur.`;
process.stdout.write(JSON.stringify({ decision: 'block', reason }));
process.exit(0);
