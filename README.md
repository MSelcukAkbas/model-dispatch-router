# AgentMind + Model Dispatch

AgentMind, ajanların ürettiği bilgiyi kodla ilişkilendiren; Codex ve Claude Code
oturumlarına ilgili bağlamı otomatik sağlayan model-dispatch-route hafıza çekirdeğidir.

## Dizinler

- `skills/model-dispatch-route/`: ana skill, dispatch scriptleri, Agent Bridge ve AgentMind çekirdeği
- `packaging/agentmind-model-dispatch-route/`: yalnızca plugin manifest/MCP şablonu
- `dist/agentmind-model-dispatch-route/`: build ile oluşan, kurulabilir plugin çıktısı (Git'e girmez)
- `docs/`: proje durumu ve araştırma notları
- `references/`: salt-okunur haricî projeler ve geçmiş kaynaklar
- `.agentmind/`, `graphify-out/`: Git'e alınmayan çalışma verisi (snapshot'lar `.agentmind/snapshots/` altında tutulur)

## Kurulum

```powershell
uv tool install --editable ".\skills\model-dispatch-route\mcp\agentmind[graph]" --force
am hooks-install . --platform all
```

`--platform codex` yalnızca Codex, `--platform claude` yalnızca Claude Code
kancalarını kurar. Kurucu mevcut kanca ayarlarını silmez; AgentMind girişlerini
birleştirir. İlk oturum başlangıcında bu depoya ait corpus ve çalışma verisi
otomatik oluşur. Bunlar Git'e alınmaz.

Rolleri özelleştirmek için `model-dispatch-route.example.json` dosyasını
`.model-dispatch-route.json` adıyla kopyalayın. Bu yerel dosyaya sır, erişim anahtarı
veya makineye özel hesap bilgisi koymayın.

## Otomatik model-dispatch-route hafızası

`model-dispatch-route`, görev başında AgentMind verisini yeniler ve görevle ilgili
bağlamı ajanın prompt'una ekler. Görev bittiğinde sonuç durumunu ve yeni
bulguları yeniden içeri alır. Bu akış için elle `am prompt` veya `am sync`
çalıştırmak gerekmez.

AgentMind geçici olarak kullanılamazsa dispatch durmaz; uyarı vererek hafızasız
devam eder. Gerekirse tek bir çağrı için `AGENTMIND_DISABLE=1` ile kapatılabilir.
Otomatik alınan iddialar aday bilgidir; doğrulanmış bilgiye yükseltme yine
`am gate` ile yapılır.

## Geliştirme

```powershell
cd skills/model-dispatch-route/mcp/agentmind
uv sync --extra graph --group dev
uv run pytest -q
```

Kurulum ve komutlar için [uygulama README'sine](skills/model-dispatch-route/mcp/agentmind/README.md), mevcut
durum ve teknik kararlar için [durum dokümanına](docs/AGENTMIND_STATE.md) bakın.

## Lisans ve dağıtım

Kurulabilir plugin, kaynak dizinin kopyası değildir. Paket üretmek için:

```powershell
node .\scripts\build-plugin.mjs
```

Bu komut yalnız `dist\agentmind-model-dispatch-route` altında çıktıyı üretir. Kod
değişiklikleri `skills\model-dispatch-route` altında, manifest değişiklikleri ise
`packaging\agentmind-model-dispatch-route` altında yapılır.

Bu depo bilinçli olarak **kapalıdır**: açık kaynak lisansı yoktur, tüm haklar
saklıdır (bkz. `LICENSE`). Bu bir eksiklik değil, tercih — dahili bir araç
olarak tutuluyor. Sonradan açılmak istenirse `LICENSE` dosyasını MIT veya
Apache-2.0 ile değiştirmek yeterli.

Uzak depo (remote) da bilinçli olarak kurulmamıştır. `.github/workflows/ci.yml`
hazır bekler ve push edildiği gün çalışır; o güne kadar aynı iki kontrol
yerelde koşturulabilir:

```bash
cd skills/model-dispatch-route/mcp/agentmind && uv run pytest -q   # birim testleri
bash scripts/smoke-test.sh                                   # taze kurulum
```

Linux tarafı Docker ile önceden doğrulanmıştır; komut `scripts/smoke-test.sh`
başlığındadır.
