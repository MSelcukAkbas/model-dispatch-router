#!/bin/bash
# usage.sh — Çok platformlu kota durumu özeti
#
# Kullanım:
#   usage.sh                        # Claude Code + AGY + Codex — tümünü kontrol et
#   usage.sh --raw                  # Claude Code için ham JSON (diğer scriptlerin kullanımına yönelik)
#   usage.sh --platform claude      # Yalnızca Claude Code
#   usage.sh --platform agy         # Yalnızca AGY (Antigravity)
#   usage.sh --platform codex       # Yalnızca Codex
#   usage.sh [--raw] [ACCOUNT]      # Geriye dönük uyumluluk: Claude hesabını belirt
#
# Kurallar:
#   - Bir platform sistemde yüklü değilse: "[platform: yüklü değil]" yazar, çıkış kodu 0.
#   - Kota sorgusu başarısız olursa: "[platform: HATA - <neden>]" yazar, çıkış kodu 0.
#     (Script kendisi başarısız olmaz; izleme scripti bir platformun çökmesiyle kesilmemeli.)
#   - --raw bayrağı yalnızca Claude Code JSON'unu döndürür (quota-watch.sh / health.sh uyumluluğu).
#   - Bilinmeyen hesap adı verilirse çıkış kodu 1 (geriye dönük uyumluluk, hata sessizce geçmez).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=account-registry.sh
source "$SCRIPT_DIR/account-registry.sh"

# ── Argüman ayrıştırma ────────────────────────────────────────────────────────
RAW=""
ACCOUNT=""
PLATFORM="all"   # all | claude | agy | codex

for arg in "$@"; do
  case "$arg" in
    --raw)       RAW="--raw" ;;
    --platform)  : ;;   # sonraki arg platform değeri olacak — shift yok, döngü sırası önemli değil
    claude|agy|codex|all)
      if [ "${PREV_ARG:-}" = "--platform" ]; then
        PLATFORM="$arg"
      else
        ACCOUNT="$arg"
      fi
      ;;
    *)
      # --platform=value biçimi
      if [[ "$arg" == --platform=* ]]; then
        PLATFORM="${arg#--platform=}"
      else
        ACCOUNT="$arg"
      fi
      ;;
  esac
  PREV_ARG="$arg"
done

# Geriye dönük uyumluluk: --raw verilmişse ve platform=all ise sadece Claude sorgula
if [ -n "$RAW" ] && [ "$PLATFORM" = "all" ]; then
  PLATFORM="claude"
fi

OVERRIDE_DIR=""
if [ -n "$ACCOUNT" ]; then
  OVERRIDE_DIR="$(resolve_account_config_dir "$ACCOUNT")" || exit 1
fi

# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

# command_exists <name>
command_exists() { command -v "$1" &>/dev/null; }

# ── Claude Code kota sorgusu ──────────────────────────────────────────────────
query_claude() {
  local raw_mode="${1:-}"   # "--raw" geçilirse ham JSON yaz
  node - "$raw_mode" "$OVERRIDE_DIR" "${ACCOUNT:-current-claude-session}" <<'NODEEOF'
const fs    = require('fs');
const https = require('https');
const path  = require('path');
const os    = require('os');

const raw         = process.argv[1] === '--raw';
const overrideDir = process.argv[2];
const label       = process.argv[3] || 'current-claude-session';
const configDir   = (overrideDir && overrideDir.length)
  ? overrideDir
  : (process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude'));
const credPath    = path.join(configDir, '.credentials.json');

let creds;
try   { creds = JSON.parse(fs.readFileSync(credPath, 'utf8')); }
catch (e) {
  console.error('NOAUTH:' + credPath + ':' + e.message);
  process.exit(2);
}

const token = creds?.claudeAiOauth?.accessToken;
if (!token) { console.error('NOAUTH:no accessToken in ' + credPath); process.exit(2); }

const req = https.request({
  hostname: 'api.anthropic.com',
  path:     '/api/oauth/usage',
  method:   'GET',
  headers:  { 'Authorization': 'Bearer ' + token, 'anthropic-beta': 'oauth-2025-04-20' }
}, res => {
  let data = '';
  res.on('data', d => data += d);
  res.on('end', () => {
    if (res.statusCode !== 200) {
      console.error('HTTP:' + res.statusCode);
      process.exit(3);
    }
    if (raw) { console.log(data); return; }
    const j      = JSON.parse(data);
    const toTR   = iso => {
      if (!iso) return 'n/a';
      const d    = new Date(iso);
      const mins = Math.round((d - new Date()) / 60000);
      return d.toISOString() + (mins > 0 ? ' (~' + mins + ' dk)' : ' (geçti)');
    };
    console.log('  [Claude Code]  hesap=' + label);
    console.log('    5 saatlik : %' + j.five_hour.utilization  + ' kullanıldı — sıfırlanma: ' + toTR(j.five_hour.resets_at));
    console.log('    7 günlük  : %' + j.seven_day.utilization  + ' kullanıldı — sıfırlanma: ' + toTR(j.seven_day.resets_at));
  });
});
req.on('error', e => { console.error('NET:' + e.message); process.exit(3); });
req.end();
NODEEOF
}

# ── AGY kota sorgusu ──────────────────────────────────────────────────────────
query_agy() {
  # agy -p "/usage" → sekme-ayrılmış satırlar:
  #   Gemini Models<TAB>Weekly Limit Remaining<TAB>56%<TAB>2026-09-10T20:01:26Z
  local raw_out
  raw_out="$(agy -p "/usage" 2>&1)"
  local exit_code=$?
  if [ "$exit_code" -ne 0 ]; then
    echo "  [AGY]  HATA — kota sorgulanamadı (çıkış kodu $exit_code)"
    return
  fi

  echo "  [AGY]"
  local now
  now=$(date +%s)
  while IFS=$'\t' read -r model_group limit_type remaining reset_at; do
    [ -z "$model_group" ] && continue
    # Kalan yüzdeyi "Remaining" ifadesini tersine çevirerek hesapla
    local pct_remaining="${remaining//%/}"
    local pct_used=$(( 100 - pct_remaining ))
    local reset_label="n/a"
    if [ -n "$reset_at" ]; then
      # node ile ISO → timestamp dönüşümü
      local reset_epoch
      reset_epoch="$(node -e "process.stdout.write(String(Math.round(new Date('$reset_at').getTime()/1000)))" 2>/dev/null || echo 0)"
      local mins_left=$(( (reset_epoch - now) / 60 ))
      if [ "$mins_left" -gt 0 ]; then
        reset_label="$reset_at (~${mins_left} dk)"
      else
        reset_label="$reset_at (geçti)"
      fi
    fi
    # Limit türünü kısalt
    local kind="$limit_type"
    if echo "$limit_type" | grep -qi "Five Hour"; then   kind="5 saatlik"; fi
    if echo "$limit_type" | grep -qi "Weekly";    then   kind="7 günlük "; fi
    echo "    $model_group — $kind : %${pct_used} kullanıldı (kalan: %${pct_remaining}) — sıfırlanma: ${reset_label}"
  done <<< "$raw_out"
}

# ── Codex kota sorgusu ────────────────────────────────────────────────────────
query_codex() {
  # Codex CLI'ının kota API'si yoktur. Sadece yüklü olup olmadığını ve
  # oturum açılıp açılmadığını `codex doctor` ile tespit ediyoruz.
  local doctor_out
  doctor_out="$(codex doctor 2>&1)"
  local exit_code=$?
  if [ "$exit_code" -ne 0 ] && ! echo "$doctor_out" | grep -qi "ok\|pass\|auth"; then
    echo "  [Codex]  HATA — codex doctor başarısız (oturum açılmamış olabilir)"
    return
  fi

  local auth_ok="✗ oturum açılmamış"
  if echo "$doctor_out" | grep -qi "auth.*ok\|logged in\|authenticated\|ok"; then
    auth_ok="✓ oturum açık"
  fi

  echo "  [Codex]  $auth_ok"
  echo "    ℹ Codex CLI'ının kota API'si bulunmamaktadır; openai.com/account/usage adresinden takip edin."
}

# ── Ana akış ─────────────────────────────────────────────────────────────────

# --raw modu: yalnızca Claude JSON (quota-watch.sh / health.sh uyumluluğu)
if [ -n "$RAW" ]; then
  if ! command_exists node; then
    echo "Node.js bulunamadı — usage.sh --raw için gerekli." >&2; exit 1
  fi
  query_claude "--raw"
  exit $?
fi

echo "═══════════════════════════════════════════════════════"
echo " Kota Durumu — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "═══════════════════════════════════════════════════════"

# Claude Code
if [ "$PLATFORM" = "all" ] || [ "$PLATFORM" = "claude" ]; then
  if ! command_exists node; then
    echo "  [Claude Code]  atlandı — node yüklü değil"
  else
    query_claude "" 2>&1 || echo "  [Claude Code]  HATA — kota sorgulanamadı"
  fi
fi

# AGY
if [ "$PLATFORM" = "all" ] || [ "$PLATFORM" = "agy" ]; then
  if ! command_exists agy; then
    echo "  [AGY]  yüklü değil — kurulum: https://antigravity.dev"
  else
    query_agy
  fi
fi

# Codex
if [ "$PLATFORM" = "all" ] || [ "$PLATFORM" = "codex" ]; then
  if ! command_exists codex; then
    echo "  [Codex]  yüklü değil — kurulum: https://github.com/openai/codex"
  else
    query_codex
  fi
fi

echo "═══════════════════════════════════════════════════════"
