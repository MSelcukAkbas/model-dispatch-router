# ⚡ Model Dispatch Route

> **Otonom Orkestratörler (Claude Code, Codex, Antigravity) için Bütçeli, İzole ve Doğrulamalı Çoklu Ajan (Multi-Agent) Yönlendirme Motoru**

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Multi--Agent: Swarm](https://img.shields.io/badge/Multi--Agent-Worktree%20Isolated-blueviolet.svg)](#-multi-agent-mimari-ve-roller)
[![CI](https://github.com/MSelcukAkbas/model-dispatch-route/actions/workflows/ci.yml/badge.svg)](https://github.com/MSelcukAkbas/model-dispatch-route/actions)

---

## 🎯 Temel Felsefe: Neden Multi-Agent Dispatch?

Karmaşık yazılım projelerinde tek bir modelin her işi yapmaya çalışması üç büyük darboğaz yaratır:
1. **Bağlam Şişmesi (Context Bloat):** Tek bir oturuma binlerce satır kod yüklendiğinde modelin odaklanma ve muhakeme kalitesi düşer.
2. **Kota ve Maliyet Patlaması:** Basit bir kod arama veya dosya tarama için en pahalı modelin token kotasını harcamak kaynak israfıdır.
3. **Doğrudan Müdahale Riski:** Bir alt ajanın ana çalışma dizininde doğrudan `git commit` veya kontrolsüz dosya değişiklikleri yapması projeyi bozabilir.

**Model Dispatch Route**, ana orkestratörü (Claude Code / Codex / Antigravity) bir **"Baş Mimar"** konumuna yerleştirir:
- 🔀 **Uzman Ajanlara Görev Delege Etme:** İşin niteliğine göre en uygun model ve efor seviyesi seçilir (kodlama için Sonnet, derin analiz için Opus, hızlı tarama için Haiku/Flash).
- 🛡️ **İzole Git Worktree Alanı:** Her alt ajan bağımsız bir Git worktree içinde çalışır. Ana çalışma dizininize doğrudan dokunamaz.
- 🔍 **Orkestratör Kontrolünde Birleştirme:** Alt ajanın ürettiği değişiklikler önce `diff.sh` ile incelenir, orkestratör onay verirse `apply.sh` ile ana dala uygulanır.
- 🧠 **AgentMind Paylaşımlı Hafıza Çekirdeği:** Ajanlar arası bilgi aktarımı sağlar; üretilen bulguları kod grafına (Graphify) mühürler ve testlerden geçmeyen iddiaları doğrulanmış saymaz (`Verification Gate`).

---

## 🏗️ Sistem Mimarisi

Aşağıdaki şema, bir görevin ana orkestratörden çıkıp alt ajanlar tarafından işlenmesini ve güvenle ana depoya dahil edilmesini gösterir:

```mermaid
%%{init: {
  'theme': 'base',
  'themeVariables': {
    'background': '#0f172a',
    'primaryColor': '#1e293b',
    'primaryTextColor': '#f8fafc',
    'primaryBorderColor': '#475569',
    'lineColor': '#94a3b8',
    'secondaryColor': '#1e293b',
    'tertiaryColor': '#0f172a',
    'clusterBkg': '#090d16',
    'clusterBorder': '#334155'
  }
}}%%
flowchart TD
    subgraph HostGroup["🖥️ ANA ORKESTRATÖR (Host)"]
        Host["Claude Code / Codex / Antigravity<br/><i>(Baş Mimar — Hedefi Belirler)</i>"]
    end

    subgraph RouterGroup["⚡ MULTI-AGENT ROUTE & ISOLATION"]
        Router["<b>dispatch.sh</b><br/><i>(Rol, Kota, Bütçe & Efor Yönlendirme)</i>"]
        Worktree["<b>Git Worktree Sandbox</b><br/><i>(Her Göreve İzole Dal: .worktrees/T-XXXXXX)</i>"]
    end

    subgraph AgentGroup["🤖 UZMAN AJAN PERSONA HAVUZU"]
        A_Backend["🔨 <b>Backend / SDK</b><br/>Sonnet · Yüksek Efor<br/><i>Kod Üretimi & Test</i>"]
        A_Design["🎨 <b>Design</b><br/>Sonnet · Yüksek Efor<br/><i>UI / Frontend / Stil</i>"]
        A_Research["🔍 <b>Research</b><br/>Haiku / Flash · Düşük Efor<br/><i>Grep / Glob / Hızlı Tarama</i>"]
        A_Judge["⚖️ <b>Judge</b><br/>Opus · Yüksek Efor<br/><i>Karar & Mimari Hakemlik</i>"]
        A_Ops["🚀 <b>Ops</b><br/>Sonnet · SSH MCP<br/><i>Sunucu & Canlı Teşhis</i>"]
    end

    subgraph ReviewGroup["🛡️ ORKESTRATÖR ONAYI & ENTEGRASYON"]
        DiffCheck["<b>diff.sh</b><br/><i>(Yamayı İncele)</i>"]
        ApplyPatch["<b>apply.sh</b><br/><i>(Ana Çalışma Ağacına Uygula)</i>"]
    end

    subgraph MemoryGroup["🧠 ORTAK BİLGİ DÜZLEMİ (AgentMind)"]
        Gate["<b>Verification Gate</b><br/><i>(Test ve Doğrulama Kontrolü)</i>"]
        Knowledge[("<b>Code Graph & Memory</b><br/><i>(SQLite + Graphify Overlay)</i>")]
    end

    Host -->|"1. Görevi Tanımla (Goal & Files)"| Router
    Router -->|"2. Sandbox Oluştur"| Worktree
    Worktree -->|"3. İşi Delege Et"| AgentGroup
    AgentGroup -->|"4. Yamayı Üret"| DiffCheck
    DiffCheck -->|"5. Onayla & Birleştir"| ApplyPatch
    ApplyPatch -->|"6. Ana Ağaca Aktar"| Host

    AgentGroup -.->|"Aday Bulguları İlet"| Gate
    Gate -->|"Doğrulanan Bilgi"| Knowledge
    Knowledge -.->|"Sonraki Göreve Bağlam Aktar"| Router

    classDef hostStyle fill:#1e293b,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;
    classDef routerStyle fill:#1e293b,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef agentStyle fill:#182234,stroke:#64748b,stroke-width:1px,color:#f8fafc;
    classDef reviewStyle fill:#1e293b,stroke:#f59e0b,stroke-width:2px,color:#f8fafc;
    classDef memoryStyle fill:#1e293b,stroke:#10b981,stroke-width:2px,color:#f8fafc;

    class Host hostStyle;
    class Router,Worktree routerStyle;
    class A_Backend,A_Design,A_Research,A_Judge,A_Ops agentStyle;
    class DiffCheck,ApplyPatch reviewStyle;
    class Gate,Knowledge memoryStyle;
```

---

## 🤖 Multi-Agent Rol Matrisi

Model Dispatch Route, görevleri rastgele bir modele göndermek yerine her rolün yetki ve kaynak sınırlarını katı kurallarla belirler:

| Rol | Varsayılan Model | Yetki Sınırları | Efor Seviyesi | Kullanım Alanı |
|---|---|---|---|---|
| **`backend`** | Sonnet | Tam Yazma / Terminal | `high` | Çekirdek iş mantığı, API geliştirme, birim testleri |
| **`design`** | Sonnet | Tam Yazma | `high` | UI/UX, CSS, bileşen düzenlemeleri, görsel estetik |
| **`sdk`** | Sonnet | Tam Yazma | `high` | Harici kütüphane, SDK ve istemci kodları |
| **`research`** | Haiku / Flash | **Salt Okunur** (Read / Grep / Glob) | `low` | Büyük depolarda hızlı kod tarama, referans arama (çok ucuz) |
| **`judge`** | Opus | **Salt Okunur** (Karar Odaklı) | `high` | Kritik mimari kararlar, çelişki çözümü, tasarım incelemesi |
| **`ops`** | Sonnet | SSH MCP / Terminal (Dosya Yazma Yok) | `high` | Uzak sunucu teşhisi, konteyner yönetimi, canlı ortam kontrolleri |
| **`general`** | Sonnet | Tam Yazma | `medium` | Dokümantasyon, konfigürasyon, görev takip dosyaları |

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
bash skills/model-dispatch-route/scripts/dispatch.sh backend TASK-101 prompt.md --timeout 20
```
- `.worktrees/TASK-101` dizini otomatik oluşturulur.
- İlgili modele özel persona yüklenir.
- Kota ve token bütçesi arka planda (`quota-watch.sh`) denetlenir.

### 3. Değişiklikleri İnceleyin (`diff.sh`)
Alt ajan işini bitirdiğinde ana deponuz bozulmaz. Üretilen yamayı orkestratör terminalinden inceleyin:
```bash
bash skills/model-dispatch-route/scripts/diff.sh TASK-101
```

### 4. Güvenle Birleştirin (`apply.sh`) veya Reddedin
```bash
# Değişiklikleri ana çalışma ağacına aktar ve worktree'yi temizle
bash skills/model-dispatch-route/scripts/apply.sh TASK-101
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
- Git ve Bash / Zsh (Windows için Git Bash / WSL veya macOS/Linux)

```bash
# 1. AgentMind CLI ve bellek çekirdeğini kurun
uv tool install --editable "./skills/model-dispatch-route/mcp/agentmind[graph]" --force

# 2. Kullandığınız host platformlara (Claude Code, Codex, Antigravity) kancaları bağlayın
am hooks-install . --platform all

# 3. Model yapılandırmasını kopyalayın
cp packaging/agentmind-model-dispatch-route/examples/model-dispatch-route.example.json .model-dispatch-route.json
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
model-dispatch-route/
├── skills/model-dispatch-route/       # ⚡ Core Multi-Agent Motoru
│   ├── SKILL.md                      # Ajan koordinasyon yönergeleri
│   ├── personas/                     # Ajan rolleri (backend, design, judge, ops, research)
│   ├── scripts/                      # dispatch.sh, diff.sh, apply.sh, status.sh
│   ├── mcp/agentmind/                # Paylaşımlı hafıza çekirdeği (SQLite, Graphify, Gate)
│   └── mcp/bridge/                   # Canlı ajan iletişim köprüsü
├── packaging/                         # 📦 Dağıtım ve Eklenti Paketleme
│   ├── agentmind-model-dispatch-route/ # Standart eklenti şablonu
│   └── build.mjs                     # Dağıtım derleyicisi
├── references/                        # 🔗 Submodule Entegrasyonları
│   └── agentic-ssh-mcp               # Ops rolü için SSH araç seti
├── docs/                             # 📚 Durum & Mimari Notları
├── .github/workflows/ci.yml           # 🧪 Çoklu Platform CI (Linux & Windows)
└── LICENSE                            # ⚖️ MIT Lisansı
```

---

## 🧪 Testler

```bash
# Python çekirdeği birim testleri (103+ test)
cd skills/model-dispatch-route/mcp/agentmind && uv run pytest -q

# Uçtan uca kurulum duman testi
bash skills/model-dispatch-route/scripts/smoke-test.sh
```

---

## 📄 Lisans

Bu proje **[MIT Lisansı](LICENSE)** ile korunmaktadır. Ticari ve kişisel kullanıma tamamen açıktır.
