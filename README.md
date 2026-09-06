# AgentMind workspace

AgentMind, ajanların ürettiği bilgiyi kodla ilişkilendiren, ilgili bağlamı
token bütçesiyle hazırlayan ve iddiaları yerel kontrollerden geçiren bir
orkestrasyon çekirdeğidir.

## Dizinler

- `skills/model-dispatch/`: ana skill, dispatch scriptleri, Agent Bridge ve AgentMind çekirdeği
- `docs/`: proje durumu ve araştırma notları
- `references/`: salt-okunur haricî projeler ve geçmiş kaynaklar
- `.agentmind/`, `snapshots/`, `graphify-out/`: Git'e alınmayan çalışma verisi

## Otomatik model-dispatch hafızası

`model-dispatch`, görev başında AgentMind verisini yeniler ve görevle ilgili
bağlamı ajanın prompt'una ekler. Görev bittiğinde sonuç durumunu ve yeni
bulguları yeniden içeri alır. Bu akış için elle `am prompt` veya `am sync`
çalıştırmak gerekmez.

AgentMind geçici olarak kullanılamazsa dispatch durmaz; uyarı vererek hafızasız
devam eder. Gerekirse tek bir çağrı için `AGENTMIND_DISABLE=1` ile kapatılabilir.
Otomatik alınan iddialar aday bilgidir; doğrulanmış bilgiye yükseltme yine
`am gate` ile yapılır.

## Geliştirme

```powershell
cd skills/model-dispatch/mcp/agentmind
uv sync --extra graph --group dev
uv run pytest -q
```

Komutları sisteme kurmak için:

```powershell
uv tool install --editable ".\skills\model-dispatch\mcp\agentmind[graph]" --force
```

Kurulum ve komutlar için [uygulama README'sine](skills/model-dispatch/mcp/agentmind/README.md), mevcut
durum ve teknik kararlar için [durum dokümanına](docs/AGENTMIND_STATE.md) bakın.
