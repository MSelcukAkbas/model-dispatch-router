#!/bin/bash
# codex-quota.sh — Codex app-server üzerinden kota sorgulama
#
# Kullanım:
#   codex-quota.sh           # insan okunabilir özet
#   codex-quota.sh --raw     # ham JSON (diğer scriptler için)
#
# Çalışma prensibi:
#   "codex app-server" sürecini başlatır, JSON-RPC üzerinden:
#     initialize → initialized → account/rateLimits/read
#   Cevaptaki primary/secondary pencereler için usedPercent ve resetsAt çeker.
#
# Çıkış kodları:
#   0  — başarılı
#   1  — codex yüklü değil
#   2  — app-server başlatılamadı veya bağlantı kapandı
#   3  — RPC hatası veya yanıt parse edilemedi
set -uo pipefail

RAW="${1:-}"

if ! command -v codex &>/dev/null; then
  echo "codex yüklü değil" >&2
  exit 1
fi

node - "$RAW" <<'NODEEOF'
const { spawn } = require('child_process');
const raw = process.argv[1] === '--raw';

// Windows Git Bash / MSYS ortamında codex doğrudan spawn edilemiyor,
// cmd.exe üzerinden çağırıyoruz (tıpkı PS1'in yaptığı gibi).
const isWindows = process.platform === 'win32' || process.env.MSYSTEM || process.env.CYGWIN;
const proc = isWindows
  ? spawn('cmd.exe', ['/c', 'codex', 'app-server'], { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true })
  : spawn('codex', ['app-server'], { stdio: ['pipe', 'pipe', 'pipe'] });

let stderr_buf = '';
proc.stderr.on('data', d => { stderr_buf += d.toString(); });

let buf = '';
let resolvers = {};  // id -> { resolve, reject }

proc.stdout.on('data', chunk => {
  buf += chunk.toString();
  const lines = buf.split('\n');
  buf = lines.pop(); // son satır henüz tamamlanmamış olabilir

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try { obj = JSON.parse(trimmed); } catch { continue; }
    const id = obj.id;
    if (id != null && resolvers[id]) {
      const r = resolvers[id];
      delete resolvers[id];
      r.resolve(obj);
    }
  }
});

function sendJson(msg) {
  proc.stdin.write(JSON.stringify(msg) + '\n');
}

function rpc(id, method, params) {
  return new Promise((resolve, reject) => {
    resolvers[id] = { resolve, reject };
    sendJson({ id, method, params: params || {} });
    // 5 saniyelik timeout
    setTimeout(() => {
      if (resolvers[id]) {
        delete resolvers[id];
        reject(new Error('RPC timeout: ' + method));
      }
    }, 5000);
  });
}

async function run() {
  // 1. Initialize
  const init = await rpc(1, 'initialize', {
    clientInfo: { name: 'codex-quota', version: '1.0.0' },
    capabilities: { experimentalApi: true }
  });

  if (init.error) throw new Error('initialize hatası: ' + init.error.message);

  // 2. Initialized bildirimi (yanıt beklenmez)
  sendJson({ method: 'initialized', params: {} });

  // 3. Rate limits
  const resp = await rpc(2, 'account/rateLimits/read');
  if (resp.error) throw new Error('rateLimits hatası: ' + resp.error.message);

  const result = resp.result;

  // Farklı Codex versiyonları farklı yapı dönebilir
  let limits = null;
  if (result.rateLimitsByLimitId && result.rateLimitsByLimitId.codex) {
    limits = result.rateLimitsByLimitId.codex;
  } else if (result.rateLimits) {
    limits = result.rateLimits;
  } else {
    throw new Error('Beklenmedik rate limits yapısı: ' + JSON.stringify(result));
  }

  if (raw) {
    console.log(JSON.stringify(limits, null, 2));
    return;
  }

  const windows = [limits.primary, limits.secondary].filter(Boolean);

  if (windows.length === 0) {
    console.error('Kota penceresi bulunamadı.');
    process.exit(3);
  }

  for (const w of windows) {
    const pctUsed      = parseFloat(w.usedPercent) || 0;
    const pctRemaining = Math.round(100 - pctUsed);
    const pctUsedInt   = Math.round(pctUsed);
    const resetDate    = new Date(w.resetsAt * 1000);
    const now          = new Date();
    const minsLeft     = Math.round((resetDate - now) / 60000);
    const resetStr     = resetDate.toISOString() + (minsLeft > 0 ? ' (~' + minsLeft + ' dk)' : ' (geçti)');
    const durMins      = parseInt(w.windowDurationMins, 10);

    let label;
    if (durMins === 300)   label = '5 saatlik';
    else if (durMins === 10080) label = '7 günlük ';
    else                   label = durMins + ' dk    ';

    console.log('    ' + label + ' : %' + pctUsedInt + ' kullanıldı (kalan: %' + pctRemaining + ') — sıfırlanma: ' + resetStr);
  }
}

run()
  .catch(err => {
    console.error('HATA: ' + err.message);
    if (stderr_buf) console.error('app-server stderr:', stderr_buf.trim());
    process.exit(3);
  })
  .finally(() => {
    try { proc.stdin.end(); proc.kill(); } catch {}
  });
NODEEOF
