# 🧩 Model Dispatch Router Plugins

Bu dizin, **Model Dispatch Router & AgentMind** çekirdeğinin farklı AI orkestratörleri için önceden paketlenmiş, "tak-kullan" eklenti (plugin) dağıtımlarını içerir.

Tüm eklentiler ana kaynak olan `skills/model-dispatch-router` dizininden `node plugins/build.mjs` ile otomatik derlenir.

---

## 📁 Dizin Yapısı

```text
plugins/
├── build.mjs                                # Saf paket derleyici (CI/CD uyumlu)
├── install.mjs                              # Kurulum ve senkronizasyon CLI
├── platforms/                               # Platform adaptörleri (codex, claude, antigravity)
├── lib/                                     # Ortak araçlar (paths, copy, logger)
│
├── codex/
│   └── agentmind-model-dispatch-router/     # OpenAI Codex CLI için eklenti
├── antigravity/
│   └── agentmind-model-dispatch-router/     # Google Antigravity (AGY) için eklenti
└── claude/
    └── agentmind-model-dispatch-router/     # Anthropic Claude Code için eklenti
```

---

## 🚀 Kurulum ve Kullanım

### Otomatik Kurulum & Senkronizasyon
```bash
# Nereye ne yazılacağını görmek için (güvenli önizleme):
npm run install:local -- --dry-run

# Yalnızca kurulu platformları güncelle (izinsiz dosya açmaz):
npm run sync

# Tüm tespit edilen araçlara ilk kurulumu yap:
npm run install:local
```

### Manuel Kurulum

#### 1. OpenAI Codex
```bash
cp -r plugins/codex/agentmind-model-dispatch-router ~/.codex/plugins/personal/
```
Veya:
```powershell
.\sync-model-dispatch-router-skill.ps1
```

#### 2. Google Antigravity (AGY)
- **Global:** `plugins/antigravity/agentmind-model-dispatch-router` klasörünü `~/.gemini/config/plugins/` altına kopyalayın.
- **Proje Bazlı:** İlgili projenin `.agents/plugins/` altına kopyalayın.

#### 3. Anthropic Claude Code
```bash
am hooks-install . --platform claude
```
Veya `plugins/claude/agentmind-model-dispatch-router` dizinini Claude plugin yolunuza ekleyin.

---

## 🔄 Yeniden Derleme (Build)

Kaynak kodda (`skills/model-dispatch-router`) yapılan bir değişiklikten sonra tüm eklentileri tek komutla güncellemek için:

```bash
npm run build
# veya: node plugins/build.mjs
```
