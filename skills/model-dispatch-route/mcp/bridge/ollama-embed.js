// ollama-embed — bge-m3 embedding katmanı, Ollama'yı KENDİSİ lazy-spawn/
// auto-kill ile yönetir; kullanıcı elle `ollama serve` çalıştırmak zorunda
// kalmaz (2026-08-23 karar — Python+torch alternatifi ölçüldü, import başına
// ~10sn ceza + ikinci runtime bağımlılığı çıktığı için reddedildi).
//
// Sabitlenen sözleşme (donanımda doğrulandı — GTX 1650 Ti, 4GB VRAM):
//   num_gpu: 999   -> tüm katmanları GPU'ya zorla (varsayılan num_ctx=4096
//                     ile CPU'ya değil GPU'ya düşünce cudaMalloc OOM
//                     veriyordu — kök neden context buffer boyutuydu,
//                     GPU'nun kendisi değil; num_ctx küçültünce çözüldü)
//   num_ctx: 4096  -> gerçek finding kayıtları ölçüldü (kısa claim: 22 token,
//                     claim+3-evidence: 196 token, abartılı 2x: 390 token) —
//                     4096, gözlenen en kötü durumun ~10 katı güvenlik payı
//                     verirken VRAM'in yarısından azını (1855/4096 MB) yer.
//                     8192 (native max) kartın %95'ini yer, kalite katkısı
//                     YOK (context sınırı sadece kesmeyi önler) — kasıtlı
//                     olarak kullanılmıyor.
//   keep_alive:10m -> model idle'da RAM/VRAM'den düşer (Ollama'nın kendi
//                     mekanizması); process'in kendisini (ollama.exe) bu
//                     dosyadaki watchdog kapatır, ayrı kaygı.
//
// Fail-soft: Ollama spawn edilemezse / embed isteği başarısız olursa `null`
// döner, İSTİSNA FIRLATMAZ — knowledge_write bunu embedding'siz (BM25-only)
// kayıt olarak kabul eder, dispatch akışı asla bloklanmaz.

'use strict';
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const REPO_ROOT = process.env.DISPATCH_REPO_ROOT
  ? path.resolve(process.env.DISPATCH_REPO_ROOT)
  : process.cwd();
const KNOWLEDGE_DIR = path.join(REPO_ROOT, '.claude', 'knowledge');
fs.mkdirSync(KNOWLEDGE_DIR, { recursive: true });
const ACTIVITY_FILE = path.join(KNOWLEDGE_DIR, '.ollama-last-used');
const WATCHDOG_PID_FILE = path.join(KNOWLEDGE_DIR, '.ollama-watchdog.pid');
const WATCHDOG_SCRIPT = path.join(__dirname, 'ollama-watchdog.js');

const OLLAMA_URL = 'http://localhost:11434';
const MODEL = 'bge-m3';
const EMBED_OPTIONS = { num_gpu: 999, num_ctx: 4096 };
const KEEP_ALIVE = '10m';
const SPAWN_READY_TIMEOUT_MS = 25000;
const REQUEST_TIMEOUT_MS = 10000;

function touchActivity() {
  try { fs.writeFileSync(ACTIVITY_FILE, String(Date.now())); } catch { /* best-effort */ }
}

async function fetchWithTimeout(url, opts, timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

async function isOllamaUp() {
  try {
    const r = await fetchWithTimeout(`${OLLAMA_URL}/api/version`, {}, 1500);
    return r.ok;
  } catch {
    return false;
  }
}

function isPidAlive(pid) {
  try {
    process.kill(pid, 0); // Windows: sinyal göndermez, sadece varlık kontrolü
    return true;
  } catch {
    return false;
  }
}

function spawnWatchdogIfNeeded() {
  try {
    if (fs.existsSync(WATCHDOG_PID_FILE)) {
      const pid = Number(fs.readFileSync(WATCHDOG_PID_FILE, 'utf8').trim());
      if (pid && isPidAlive(pid)) return; // zaten çalışıyor
    }
  } catch { /* pidfile bozuksa yeniden spawn et */ }
  try {
    const child = spawn(process.execPath, [WATCHDOG_SCRIPT], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    });
    child.unref();
    fs.writeFileSync(WATCHDOG_PID_FILE, String(child.pid));
  } catch { /* watchdog spawn edilemezse sorun değil — model idle'da zaten kendi düşer, sadece process ayakta kalır */ }
}

async function ensureOllama() {
  if (await isOllamaUp()) {
    touchActivity();
    spawnWatchdogIfNeeded(); // idempotent — pidfile zaten canlıysa no-op
    return true;
  }
  try {
    const child = spawn('ollama', ['serve'], { detached: true, stdio: 'ignore', windowsHide: true });
    child.unref();
  } catch {
    return false; // ollama binary PATH'te yok — fail-soft, embed'siz devam
  }
  spawnWatchdogIfNeeded();
  const deadline = Date.now() + SPAWN_READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await isOllamaUp()) {
      touchActivity();
      return true;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

/**
 * @param {string} text
 * @returns {Promise<number[]|null>} 1024-boyutlu normalize vektör, ya da
 *   Ollama erişilemezse null (fail-soft — asla throw etmez).
 */
async function embed(text) {
  try {
    const up = await ensureOllama();
    if (!up) return null;
    const res = await fetchWithTimeout(`${OLLAMA_URL}/api/embed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: MODEL, input: text, options: EMBED_OPTIONS, keep_alive: KEEP_ALIVE }),
    }, REQUEST_TIMEOUT_MS);
    if (!res.ok) return null;
    const j = await res.json();
    touchActivity();
    return (j.embeddings && j.embeddings[0]) || null;
  } catch {
    return null;
  }
}

module.exports = { embed, touchActivity, ACTIVITY_FILE };
