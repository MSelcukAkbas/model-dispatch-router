// ollama-watchdog — ollama-embed.js tarafından detached+unref spawn edilir,
// dispatch'in kendi ömründen (25dk) bağımsız uzun süre yaşar. Tek işi: N
// dakika hiç embed çağrısı gelmezse `ollama.exe`'yi kapatıp kendi kendine
// çıkmak — kullanıcının "Ollama sürekli açık kalmasın" isteği (2026-08-23).
//
// Neden ayrı process: agent-bridge.js instance'ları per-dispatch kısa ömürlü
// (task biter bitmez ölür) — hiçbiri tek başına "tüm task'lar arasında 15dk
// idle" durumunu gözlemleyemez. Bu script o gözlemi bridge'lerin ömründen
// bağımsız olarak yapar.

'use strict';
const path = require('path');
const fs = require('fs');
const { execFile } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..');
const KNOWLEDGE_DIR = path.join(REPO_ROOT, '.claude', 'knowledge');
const ACTIVITY_FILE = path.join(KNOWLEDGE_DIR, '.ollama-last-used');
const PID_FILE = path.join(KNOWLEDGE_DIR, '.ollama-watchdog.pid');

const IDLE_LIMIT_MS = 15 * 60 * 1000; // 15dk
const POLL_MS = 60 * 1000; // 1dk

function readLastUsed() {
  try {
    return Number(fs.readFileSync(ACTIVITY_FILE, 'utf8').trim()) || 0;
  } catch {
    return 0;
  }
}

function killOllama() {
  return new Promise((resolve) => {
    execFile('taskkill', ['/F', '/IM', 'ollama.exe'], () => resolve());
  });
}

function cleanupPidFile() {
  try {
    const owner = Number(fs.readFileSync(PID_FILE, 'utf8').trim());
    if (owner === process.pid) fs.unlinkSync(PID_FILE);
  } catch { /* zaten yoksa ya da başka bir watchdog'a aitse dokunma */ }
}

async function loop() {
  for (;;) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    const lastUsed = readLastUsed();
    if (lastUsed === 0) continue; // hiç aktivite kaydı yok — bekle
    if (Date.now() - lastUsed >= IDLE_LIMIT_MS) {
      await killOllama();
      cleanupPidFile();
      process.exit(0);
    }
  }
}

loop();
