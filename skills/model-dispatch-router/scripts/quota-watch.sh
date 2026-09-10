#!/bin/bash
# quota-watch.sh — 3 platform (Claude Code, AGY, Codex) için sürekli kota izleme
#
# Kullanım:
#   quota-watch.sh [ACCOUNT] [POLL_SECONDS]
#     ACCOUNT      Claude hesabı (opsiyonel, accounts.sh kayıt defterinden)
#     POLL_SECONDS Yoklama aralığı (varsayılan: 300 = 5 dakika)
#
# Çalışma şekli:
#   - Arka planda başlatılır (run_in_background:true / IsDaemon:true).
#   - Her 5 dakikada bir her platform için kota sorgular.
#   - Yalnızca yüklü platformları izler; olmayan platformlar "yüklü değil" olarak bir kez bildirilir.
#   - Her %5'lik bant geçişinde (yukarı ya da aşağı) bir satır yazar → Monitor tool ile bildirim alırsınız.
#   - Hiçbir bant değişmediği yoklamalar sessiz geçer — Monitor spam yapmaz.
#   - MAX_HOURS (varsayılan 8) sonra kendiliğinden durur (güvenlik kapağı).
#   - Claude Code 5 saatlik kotası %90'ı aşarsa ayrıca uyarı verir.
#
# Session başında başlatın:
#   bash skills/model-dispatch-router/scripts/quota-watch.sh &
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ACCOUNT="${1:-}"
POLL="${2:-300}"
MAX_HOURS="${QUOTA_WATCH_MAX_HOURS:-8}"

DEADLINE=$(( $(date +%s) + MAX_HOURS * 3600 ))

# ── Bant takip değişkenleri (her platform için ayrı) ──────────────────────────
LAST_BAND_CLAUDE=-1
LAST_BAND_AGY_GEMINI=-1
LAST_BAND_AGY_CLAUDE_GPT=-1
NOTIFIED_CODEX=0

# ── Yardımcı: Claude 5 saatlik kullanım yüzdesini al ─────────────────────────
get_claude_util() {
  local raw
  raw="$(bash "$SCRIPT_DIR/usage.sh" --raw "$ACCOUNT" 2>&1)"
  [ $? -ne 0 ] && echo "-1" && return
  node -e "
    try {
      const j = JSON.parse(process.argv[1]);
      process.stdout.write(String(j.five_hour.utilization));
    } catch(e) { process.stdout.write('-1'); }
  " -- "$raw" 2>/dev/null || echo "-1"
}

# ── Yardımcı: AGY kota satırlarını al (model_group\tutilization\tresets_at) ──
get_agy_lines() {
  # agy çıktısı: "Gemini Models\tFive Hour Limit Remaining\t44%\t2026-..."
  agy -p "/usage" 2>/dev/null | while IFS=$'\t' read -r model_group limit_type remaining reset_at; do
    [ -z "$model_group" ] && continue
    if echo "$limit_type" | grep -qi "Five Hour"; then
      local pct_used=$(( 100 - ${remaining//%/} ))
      echo "${model_group}__5h\t${pct_used}\t${reset_at}"
    fi
  done
}

# ── Yardımcı: komut yüklü mü? ────────────────────────────────────────────────
command_exists() { command -v "$1" &>/dev/null; }

# ── İlk başlangıç mesajı ─────────────────────────────────────────────────────
echo "quota-watch: başlatıldı — $(date '+%Y-%m-%d %H:%M:%S'), ${MAX_HOURS}h güvenlik kapağı, ${POLL}s aralık"

# Yüklü olmayan platformları bir kez bildir
command_exists agy    || echo "quota-watch: [AGY] yüklü değil — izlenmeyecek"
command_exists codex  || echo "quota-watch: [Codex] yüklü değil — kota API'si de yok, izlenmeyecek"
command_exists node   || echo "quota-watch: [Claude Code] node yüklü değil — izlenmeyecek"

# ── Ana döngü ─────────────────────────────────────────────────────────────────
while true; do
  # Güvenlik kapağı kontrolü
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "quota-watch: ${MAX_HOURS}h güvenlik kapağına ulaşıldı — duruluyor."
    exit 0
  fi

  NOW="$(date '+%H:%M:%S')"

  # ── Claude Code ────────────────────────────────────────────────────────────
  if command_exists node; then
    UTIL="$(get_claude_util)"
    if [ "$UTIL" = "-1" ]; then
      echo "quota-watch [${NOW}]: [Claude Code] kota sorgulanamadı"
    else
      BAND=$(( ${UTIL%.*} / 5 * 5 ))
      if [ "$BAND" != "$LAST_BAND_CLAUDE" ]; then
        MSG="quota-watch [${NOW}]: [Claude Code] 5 saatlik → %${UTIL} kullanıldı"
        # %90 uyarı eşiği
        if awk -v u="$UTIL" 'BEGIN{exit (u >= 90) ? 0 : 1}'; then
          MSG="$MSG ⚠ YÜKSEK KOTA — dispatch.sh yeni görev almayı reddeder, wait-quota.sh kullanın"
        fi
        echo "$MSG"
        LAST_BAND_CLAUDE="$BAND"
      fi
    fi
  fi

  # ── AGY ────────────────────────────────────────────────────────────────────
  if command_exists agy; then
    while IFS=$'\t' read -r key pct_used reset_at; do
      [ -z "$key" ] && continue
      BAND=$(( ${pct_used%.*} / 5 * 5 ))
      # Hangi bant değişkeni? Gemini vs Claude&GPT
      if echo "$key" | grep -qi "Gemini"; then
        LAST_VAR="LAST_BAND_AGY_GEMINI"
        CUR="${LAST_BAND_AGY_GEMINI}"
        LABEL="Gemini (5h)"
      else
        LAST_VAR="LAST_BAND_AGY_CLAUDE_GPT"
        CUR="${LAST_BAND_AGY_CLAUDE_GPT}"
        LABEL="Claude&GPT (5h)"
      fi
      if [ "$BAND" != "$CUR" ]; then
        echo "quota-watch [${NOW}]: [AGY] ${LABEL} → %${pct_used} kullanıldı — sıfırlanma: ${reset_at:-n/a}"
        eval "${LAST_VAR}=${BAND}"
      fi
    done < <(get_agy_lines)
  fi

  # ── Codex ──────────────────────────────────────────────────────────────────
  # Codex'in kota API'si yok; yalnızca ilk tur auth durumunu bildir
  if command_exists codex && [ "$NOTIFIED_CODEX" = "0" ]; then
    local_auth_ok=0
    codex doctor 2>&1 | grep -qi "auth.*ok\|logged in\|authenticated\|ok" && local_auth_ok=1
    if [ "$local_auth_ok" = "1" ]; then
      echo "quota-watch [${NOW}]: [Codex] oturum açık — kota API'si yok, openai.com/account/usage adresini kontrol edin"
    else
      echo "quota-watch [${NOW}]: [Codex] oturum açılmamış — kota izlenemez"
    fi
    NOTIFIED_CODEX=1
  fi

  sleep "$POLL"
done
