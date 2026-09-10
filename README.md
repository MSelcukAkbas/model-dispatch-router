# ⚡ Model Dispatch Router

> **Otonom Orkestratörler (Claude Code, Codex, Antigravity) için Bütçeli, İzole ve Doğrulamalı Çoklu Ajan (Multi-Agent) Yönlendirme Motoru**

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Multi--Agent: Swarm](https://img.shields.io/badge/Multi--Agent-Worktree%20Isolated-blueviolet.svg)](#-multi-agent-mimari-ve-roller)
[![CI](https://github.com/MSelcukAkbas/model-dispatch-router/actions/workflows/ci.yml/badge.svg)](https://github.com/MSelcukAkbas/model-dispatch-router/actions)

---

## 🎯 Temel Felsefe: Neden Multi-Agent Dispatch?

Karmaşık yazılım projelerinde tek bir modelin her işi yapmaya çalışması üç büyük darboğaz yaratır:
1. **Bağlam Şişmesi (Context Bloat):** Tek bir oturuma binlerce satır kod yüklendiğinde modelin odaklanma ve muhakeme kalitesi düşer.
2. **Kota ve Maliyet Patlaması:** Basit bir kod arama veya dosya tarama için en pahalı modelin token kotasını harcamak kaynak israfıdır.
3. **Doğrudan Müdahale Riski:** Bir alt ajanın ana çalışma dizininde doğrudan `git commit` veya kontrolsüz dosya değişiklikleri yapması projeyi bozabilir.

**Model Dispatch Router**, ana orkestratörü (Claude Code / Codex / Antigravity) bir **"Baş Mimar"** konumuna yerleştirir:
- 🔀 **Uzman Ajanlara Görev Delege Etme:** İşin niteliğine göre en uygun model ve efor seviyesi seçilir (kodlama için Sonnet, derin analiz için Opus, hızlı tarama için Haiku/Flash).
- 🛡️ **İzole Git Worktree Alanı:** Her alt ajan bağımsız bir Git worktree içinde çalışır. Ana çalışma dizininize doğrudan dokunamaz.
- 🔍 **Orkestratör Kontrolünde Birleştirme:** Alt ajanın ürettiği değişiklikler önce `diff.sh` ile incelenir, orkestratör onay verirse `apply.sh` ile ana dala uygulanır.
- 🧠 **AgentMind Paylaşımlı Hafıza Çekirdeği:** Ajanlar arası bilgi aktarımı sağlar; üretilen bulguları kod grafına (Graphify) mühürler ve testlerden geçmeyen iddiaları doğrulanmış saymaz (`Verification Gate`).

---

## 🏗️ Sistem Mimarisi

Aşağıdaki şema, bir görevin ana orkestratörden çıkıp alt ajanlar tarafından işlenmesini ve güvenle ana depoya dahil edilmesini gösterir:

```mermaid
flowchart TD
    Host["Host Orkestratör: Claude Code / Codex / Antigravity"]
    Router["Model Dispatch Router: Görev Yönlendirme & Worktree"]
    Agents["Multi-Agent Çalışan Modeller (Uzman Ajanlar)"]
    Memory[("AgentMind Ortak Hafıza: Code Graph, SQLite & Gate")]

    Host -->|"1. Görev Tanımla"| Router
    Router -->|"2. İzole Sandbox Çalıştır"| Agents
    Agents <-->|"3. Ortak Hafıza Erişimi & Doğrulama"| Memory
    Agents -->|"4. Onaylanan Çözüm & Yama"| Host
```

---

## 🤖 Multi-Agent Rol Matrisi

Model Dispatch Router, görevleri rastgele bir modele göndermek yerine her rolün yetki ve kaynak sınırlarını katı kurallarla belirler:

| Rol | Varsayılan Model | Yetki Sınırları | Efor Seviyesi | Kullanım Alanı |
|---|---|---|---|---|
| **`backend`** | Sonnet 5 | Tam Yazma / Terminal | `high` | Çekirdek iş mantığı, API geliştirme, birim testleri |
| **`design`** | Sonnet 5 | Tam Yazma | `high` | UI/UX, CSS, bileşen düzenlemeleri, görsel estetik |
| **`sdk`** | Sonnet 5 | Tam Yazma | `high` | Harici kütüphane, SDK ve istemci kodları |
| **`research`** | Haiku / Gemini 3.8 Flash | **Salt Okunur** (Read / Grep / Glob) | `low` | Büyük depolarda hızlı kod tarama, referans arama (çok ucuz) |
| **`judge`** | Opus 4.8 / Gemini 3.1 Pro | **Salt Okunur** (Karar Odaklı) | `high` | Kritik mimari kararlar, çelişki çözümü, bağımsız inceleme |
| **`ops`** | Sonnet 5 | SSH MCP / Terminal (Dosya Yazma Yok) | `high` | Uzak sunucu teşhisi, konteyner yönetimi, canlı ortam kontrolleri |
| **`general`** | Sonnet 5 | Tam Yazma | `medium` | Dokümantasyon, konfigürasyon, görev takip dosyaları |


---

## ⚡ Multi-Agent Çalışma Akışı (Lifecycle)

### 1. Görevi Hazırlayın (`prompt.md`)
Her görevin en başında **tek bir net hedef** ve isteğe bağlı **hedef dosyalar** tanımlanır:
```markdown
# GOAL: Auth middleware'ine JWT token doğrulama mantığını ekle ve testlerini yaz
# FILES: src/middleware/auth.ts,tests/auth.test.ts

Detaylı gereksinimler...
```

### 2. Ajanı Göreve Gönderin (`dispatch.sh`)
```bash
# Backend ajanı izole bir worktree içinde işe başlar
bash skills/model-dispatch-router/scripts/dispatch.sh backend TASK-101 prompt.md --timeout 20
```
- `.worktrees/TASK-101` dizini otomatik oluşturulur.
- İlgili modele özel persona yüklenir.
- Kota ve token bütçesi arka planda (`quota-watch.sh`) denetlenir.

### 3. Değişiklikleri İnceleyin (`diff.sh`)
Alt ajan işini bitirdiğinde ana deponuz bozulmaz. Üretilen yamayı orkestratör terminalinden inceleyin:
```bash
bash skills/model-dispatch-router/scripts/diff.sh TASK-101
```

### 4. Güvenle Birleştirin (`apply.sh`) veya Reddedin
```bash
# Değişiklikleri ana çalışma ağacına aktar ve worktree'yi temizle
bash skills/model-dispatch-router/scripts/apply.sh TASK-101
```

---

## 🧠 Ortak Hafıza & Doğrulama Kapısı (AgentMind)

Multi-agent sistemlerinde ajanların birbirinin yaptığı işlerden haberdar olması için AgentMind bir arka plan bellek motoru olarak çalışır:

* **Sıfır Halüsinasyon (`am gate`):** Alt ajanın "Bu sorunu çözdüm" şeklindeki iddiası hemen doğru sayılmaz (`candidate`). Ancak testten geçerse doğrulanır:
  ```bash
  am gate TASK-101 --check "npm test" --promote
  ```
* **Otomatik Geçersiz Kılma (Freshness):** Doğrulanan bilgi, dayandığı dosyaların hash'i ile mühürlenir. İlgili dosyalar gelecekte değiştiğinde eski iddia anında `stale` statüsüne düşer.
* **Fail-Open Garantisi:** Hafıza servisi geçici olarak kapalı olsa dahi model dispatch akışı kilitlenmez; uyarı vererek çalışmaya devam eder.

---

## 📦 Kurulum

### Gereksinimler
- Python `>=3.12, <3.13`
- [uv](https://docs.astral.sh/uv/)
- Node.js `>=18` (npm)
- Git ve Bash / Zsh (Windows için Git Bash / WSL veya macOS/Linux)

```bash
# 1. Depoyu klonlayın ve dizine geçin
git clone https://github.com/MSelcukAkbas/model-dispatch-router.git
cd model-dispatch-router

# 2. Bağımlılıkları kurun ve eklenti paketlerini derleyin
npm install
npm run build

# 3. AgentMind CLI ve bellek çekirdeğini kurun
uv tool install --editable "./skills/model-dispatch-router/mcp/agentmind[graph]" --force

# 4. Kullandığınız host platformlara (Claude Code, Codex, Antigravity) kancaları bağlayın
am hooks-install . --platform all

# 5. Örnek model yapılandırmasını kopyalayın
cp skills/model-dispatch-router/templates/model-dispatch-router.example.json .model-dispatch-router.json
```

---

## 🎮 Platform Uyumluluğu

| Platform | Entegrasyon Yöntemi | Sağlanan Yetenekler |
|---|---|---|
| **Antigravity (`agy`)** | `.agents/plugins/marketplace.json` | Skill entegrasyonu, arka plan alt-ajan yönetimi, memory injection |
| **Claude Code** | `.claude/settings.json` | `SessionStart` / `SessionEnd` bellek kancaları, persona bazlı dispatch |
| **Codex** | `.codex/hooks.json` | Eklenti manifesti, izole sandbox yürütme |

---

## 📂 Dizin Ağacı

```
model-dispatch-router/
├── skills/model-dispatch-router/       # ⚡ Core Multi-Agent Motoru (Tek Kaynak / Source of Truth)
│   ├── SKILL.md                      # Ajan koordinasyon yönergeleri
│   ├── personas/                     # Ajan rolleri (backend, design, judge, ops, research)
│   ├── scripts/                      # dispatch.sh, diff.sh, apply.sh, status.sh ve testler
│   ├── mcp/agentmind/                # Paylaşımlı hafıza çekirdeği (SQLite, Graphify, Gate)
│   └── mcp/bridge/                   # Canlı ajan iletişim köprüsü
├── plugins/                           # 📦 Eklenti Dağıtımları ve Araçları
│   ├── claude/                       # Claude Code eklenti çıktısı
│   ├── codex/                        # OpenAI Codex eklenti çıktısı
│   ├── antigravity/                  # Antigravity eklenti çıktısı
│   ├── platforms/                    # Platform adaptörleri
│   ├── build.mjs                     # Eklenti derleyicisi
│   └── install.mjs                   # Kurulum & senkronizasyon yöneticisi
├── references/                        # 🔗 Submodule Entegrasyonları
│   └── agentic-ssh-mcp               # Ops rolü için SSH araç seti
├── docs/                             # 📚 Durum, Çözüm & Mimari Notları
├── .github/workflows/ci.yml           # 🧪 Çoklu Platform CI (Linux & Windows - Node & Python)
└── LICENSE                            # ⚖️ MIT Lisansı
```

---

## 🧪 Testler

```bash
# Tüm testleri (Node eklenti derleme & Python çekirdeği) çalıştırma:
npm test

# Sadece Python çekirdeği birim testleri (103+ test):
npm run test:python   # veya cd skills/model-dispatch-router/mcp/agentmind && uv run pytest -q

# Sadece Node.js / script testleri:
npm run test:node

# Uçtan uca kurulum duman testi (Bash):
bash skills/model-dispatch-router/scripts/smoke-test.sh
```

---

## 📄 Lisans

Bu proje **[MIT Lisansı](LICENSE)** ile korunmaktadır. Ticari ve kişisel kullanıma tamamen açıktır.
