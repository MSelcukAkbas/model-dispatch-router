# Model Dispatch Entegrasyon ve Yapılandırma Şablonları

Bu dizin, hem yapay zeka modelleri (Claude Code, Codex, Antigravity) hem de geliştiriciler için hazır, "tak-kullan" şablon dosyaları içerir.

## Dosya Dağılımı ve Kullanımı

| Şablon Dosyası | Hedef Konum | Açıklama |
|---|---|---|
| `hooks/claude-settings.json` | `<proje-kökü>/.claude/settings.json` | Claude Code için SessionStart & SessionEnd bellek yaşam döngüsü kancaları. |
| `hooks/codex-hooks.json` | `<proje-kökü>/.codex/hooks.json` | Codex için SessionStart & SessionEnd bellek yaşam döngüsü kancaları. |
| `mcp/mcp.json` | `<proje-kökü>/.mcp.json` | AgentMind MCP (`agentmind-mcp`) sunucu bağlantısı. |
| `plugin/plugin.json` | `<proje-kökü>/.codex-plugin/plugin.json` | Codex ve Antigravity için eklenti (plugin) manifest tanımı. |
| `model-dispatch-router.example.json` | `<proje-kökü>/.model-dispatch-router.json` | Görev doğrulama (`verifyCommand`), roller ve bütçe sınırları ayarları. |

## Hızlı Kurulum

Kancaları otomatik olarak kurmak için:
```bash
# Claude ve Codex kancalarını birlikte kurar
am hooks-install . --platform all

# Sadece Claude Code için
am hooks-install . --platform claude

# Sadece Codex için
am hooks-install . --platform codex
```

Manuel kurulum için ilgili şablon dosyasını projenin hedef dizinine kopyalamanız yeterlidir.
