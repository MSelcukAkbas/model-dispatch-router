---
name: model-dispatch
description: Kod, araştırma, tasarım, SDK, operasyon ve değerlendirme görevlerini ayrı model oturumlarına ve güvenli git worktree'lerine dağıtır; sonuçları Agent Bridge ile toplar ve AgentMind hafızasını görev başlangıcı ile bitişinde otomatik senkronize eder. Kullanıcı bir işi alt modele devretmek, paralel ajan çalıştırmak, worktree patch akışı kullanmak veya model-dispatch çağırmak istediğinde kullan.
---

# model-dispatch — headless karakterli paralel model dağıtımı

Bu skill, bugün elle yapılan "3 ayrı Claude Code penceresine prompt ver, çıktıyı
kopyala-yapıştır al" iş akışını otomatikleştirir. Her rol (backend/design/sdk)
sabit bir karaktere (`(.claude/skills/model-dispatch/personas/<rol>.md`) sahip, headless `claude -p`
ile ayrı bir git worktree'de, arka planda, `bypassPermissions` (MCP tool'ları
dahil tam yetki) ile çalışır — ama **commit/push/branch-silme/rm -rf
`--disallowedTools` ile engellenmiş**, sadece dosya düzenler. Bu bir
prefix-match denylist, sandbox DEĞİL (2026-07-30 netleştirildi) — `git -C x
commit`, `sh -c "git push"` gibi kaçamaklar teknik olarak mümkün, listede
tek tek enumerate edilmemiş her varyant aynı boşluğu taşır (bkz.
`dispatch.sh`'taki `DISALLOWED` tanımı ve `personas/ops.md`'nin SSH için
söylediği aynı dürüst uyarı). Asıl güvence bu liste değil, apply.sh'tan
ÖNCE diff review'dur.

## AgentMind otomatik yaşam döngüsü

`dispatch.sh`, AgentMind hafızasını görev yaşam döngüsüne otomatik bağlar:

- Başlangıçta `am session-start` çalışır; depo senkronize edilir ve görevle
  ilgili kod-grafı/önceki iddia bağlamı ajanın prompt'una eklenir.
- Dispatch edilen ajana `agentmind` MCP sunucusu da verilir; ajan gerektiğinde
  dosya veya görev bazlı hafızayı ayrıca sorgulayabilir.
- Bitişte `am session-end` çalışır; sonuç durumu kaydedilir ve yeni bulgular
  içeri alınır.

Bu entegrasyon fail-open'dır: `am` veya `agentmind-mcp` bulunamazsa görev
hafızasız devam eder. Geçici olarak kapatmak için `AGENTMIND_DISABLE=1`
kullanılabilir. AgentMind bağlamındaki `candidate` iddialar yalnızca araştırma
ipucudur; `am gate` doğrulaması olmadan gerçek kabul edilmez.

**Kritik kural: dispatch edilen ajan asla commit/push atmaz, hiçbir şey
silmez.** Orkestratör (sen — ana Claude oturumu) çıktıyı okur, diff'i
inceler, ana checkout'a uygular, kullanıcıya rapor eder — commit kararı
her zaman kullanıcı onayıyla ana oturumda alınır (mevcut gorev-loop akışıyla
birebir aynı disiplin, sadece dispatch/collect adımı script'lenmiş).

## Orkestratörün rolü — orkestra şefi disiplini (2026-08-03)

Bu skill'i kullanan ana oturum bir orkestra şefi gibi davranır: işi kendisi
ÇALMAZ — Edit/Write/Bash ile doğrudan kod/doküman değişikliği yapmaz, rolleri
dağıtır, `diff.sh` ile sonuçları inceler, `apply.sh` ile ana checkout'a
taşır, kararı verir, kullanıcıya raporlar.

"Çok basit, direkt ben yaparım" refleksi — küçük/mekanik görünen fix'ler
dahil — dispatch disiplinini es geçmenin en yaygın yolu. Dokunulacak alan
hiçbir role net girmese bile `general` rolü tam bunun için var (bkz.
"Roller").

**İstisnalar — orkestratörün kendisinin iş yapması makul olduğu üç durum,
başka yok:**
- Değişiklik gerçekten trivial ki dispatch overhead'i (worktree açma, prompt
  dosyası yazma, bekleme) değerine değmez — tek karakterlik typo gibi.
- Görev canlı kullanıcı diyaloğuna/onayına bağlı — headless bir ajan soru
  soramaz (bkz. "Prompt formatı — tek hedef zorunlu"), dispatch edilemez.
- Salt-okunur bir teşhis/arama adımı (Read/Grep/Glob ile bilgi toplama) —
  bunlar zaten "iş yapmak" değil, dispatch kararının kendisini besleyen ön
  adım.

Orkestratörün kendi context penceresi/kotası işi YAPMAK için değil, işi
YÖNETMEK (dağıtma, diff inceleme, karar, kullanıcı iletişimi) için
harcanmalı.

## ⚠️ Kritik sınırlama: dispatch edilen ajan SENİN commit'lenmemiş
## değişikliklerini GÖRMEZ (2026-07-17, kendi-denetim'de bulundu)

`dispatch.sh` her task için `git worktree add -b "$BRANCH" "$WORKTREE_DIR"
HEAD` çalıştırıyor — bu, git'in normal davranışı gereği yeni worktree'ye
SADECE en son commit'lenmiş durumu kopyalıyor. Ana checkout'ta (senin şu an
üzerinde çalıştığın working tree'de) commit'lenmemiş HERHANGİ bir değişiklik
— staged ya da unstaged fark etmez — dispatch edilen ajana GÖRÜNMÜYOR. Ajan
o dosyaların ESKİ (son commit'teki) halini görüyor, senin az önce yaptığın
düzenlemeyi hiç bilmiyor.

**Somut sonuç:** Bu repoda "sadece istenince commit at" kuralı var (bkz. ana
CLAUDE.md), yani normal çalışma hali genelde commit'lenmemiş değişikliklerle
dolu working tree. Böyle bir anda dispatch edilen HER task — bu skill'in
kendi script'lerini denetlemek için dispatch edilen research/judge task'ları
dahil, 2026-07-17'de bizzat böyle oldu — senin üzerinde çalıştığın güncel
kodu değil, en son commit'teki halini görür.

**Ne yapmalı:**
- Dispatch edeceğin task'ın dokunacağı alanda senin (orkestratörün) henüz
  commit'lenmemiş bir değişikliği varsa — ya önce o değişikliği commit'le
  (kullanıcı onayıyla, her zamanki gibi), ya da task'ın prompt'una bu
  dosyaların GÜNCEL içeriğini elle yapıştır, ya da `git stash create` +
  `git worktree add` sonrası `git -C "$WORKTREE_DIR" stash apply <stash>`
  ile commit'siz diff'i worktree'ye taşı (script'lere henüz eklenmedi —
  elle yapılması gerekiyor).
- Kendi kod tabanını (ör. bu skill'in kendisini) denetlemek/geliştirmek
  için dispatch ediyorsan, ÖNCE mevcut commit'lenmemiş çalışmanı commit'le
  (kullanıcı onayıyla), SONRA dispatch et — aksi halde ajan eski kodu
  denetler, bulguları güncel duruma uymaz.

## ⚠️ İkinci sınırlama: worktree ana repo'da TRACK EDİLMEYEN/iç içe repo
## klasörlere hiç erişemez (2026-07-28'de bulundu)

Aynı köke sahip ayrı bir sorun: `git worktree add` sadece ana repo'nun HEAD'inde
TRACK EDİLEN dosyaları kopyalar. `sdks/` bu repoda tamamen `.gitignore`'da
(ana repo onun altında sıfır dosya track ediyor) VE kendisi ayrı bir git
repo — üstüne `sdks/android/arviskyccallsdk` / `arviskycfacesdk` /
`arviskycnfcsdk` / `arviskycocrsdk` de `sdks/.gitignore`'da ayrıca ignore
edilmiş, kendi başlarına birer git repo (3 katman iç içe). Sonuç: `sdk`
rolüyle normal (worktree'li) dispatch edilen bir task'ın worktree'sinde
`sdks/` klasörü HİÇ YOK — ajan tam yazma yetkisine sahip olsa da
`sdks/android/arviskyccallsdk` gibi bir yola dokunamaz, çünkü o worktree'de
o yol fiziksel olarak mevcut değil.

**Çözüm — `no-worktree` parametresi:** `dispatch.sh`'ın 7. (opsiyonel)
argümanı `no-worktree` — `1` verilirse worktree hiç açılmaz, `RUN_DIR`
doğrudan ana checkout (`$REPO_ROOT`) olur, tıpkı readonly rollerin zaten
yaptığı gibi. Ajanın cwd'si gerçek working tree olduğu için `sdks/...`
altındaki her şey fiziksel olarak orada VE erişilebilir. `sdk` rolüyle
`sdks/` altına dokunan HER task bu bayrakla dispatch edilmeli:
```bash
dispatch.sh sdk kyc-xxx .agent-logs/prompts/kyc-xxx.txt 25 high "" 1
```
(6. argüman — budget-usd — boş bırakılmalı, önce onu doldurmadan 7.'ye
geçilemez; boş string varsayılan seed budget'ı kullanır.)

**Bedelleri (bilerek kabul edilmiş, üstünkörü değil):**
- İzolasyon yok — aynı anda çalışan başka bir no-worktree task ya da
  orkestratörün kendi commit'lenmemiş çalışmasıyla çakışabilir (aynı
  `# FILES:` çakışma kontrolü burada da geçerli, ona güven).
- `diff.sh`/`apply.sh` bu task'lar için no-op'a döner (exit 0, "zaten
  diskte, git -C <yol> status/diff ile bak" mesajıyla) — ayrı bir
  worktree kopyası olmadığı için incelenecek/kopyalanacak ayrı bir diff
  yok, değişiklik doğrudan gerçek working tree'de.
- Kaçak-kota clamp'inin ilerleme-bazlı halving/exit-19 mantığı bu task'lar
  için devre dışı (izole diff tabanı olmadan "ilerleme oldu mu" ölçülemez)
  — flat seed budget her attempt'te (readonly rollerle aynı davranış, bkz.
  "Kaçak kota yakımı").
- `resume.sh` bu modu `$TASK.meta`'dan otomatik okuyup taşır — tekrar
  belirtmene gerek yok.

`sdk` rolü DIŞINDA da her rol bu bayrağı alabilir (jenerik parametre) —
ama şu an bilinen tek gerçek kullanım nedeni sdks/'in bu iç-içe-repo yapısı.

## Roller

| Rol | Model | Tool erişimi | Kapsam | Persona dosyası |
|-----|-------|--------------|--------|------------------|
| `backend` | Sonnet 5 | tam (bypassPermissions, MCP dahil) | services/gateway, kyc-engine, communication, identity-service, sdk-gateway | `.claude/skills/model-dispatch/personas/backend.md` |
| `design` | Sonnet 5 | tam | portals/ops-dashboard, portals/admin-portal (frontend) | `.claude/skills/model-dispatch/personas/design.md` |
| `sdk` | Sonnet 5 | tam | sdks/ (host test app) + sdks/android/{arviskyccallsdk,arviskycfacesdk,arviskycnfcsdk,arviskycocrsdk} (embedded SDK repos) — bkz. "no-worktree parametresi" bölümü, bu kapsamda worktree değil no-worktree=1 gerekir | `.claude/skills/model-dispatch/personas/sdk.md` |
| `general` | Sonnet 5 | tam | catch-all — Dokumanlar/*.md ticket editi, config, script, root-level dosyalar; backend/design/sdk kapsamına girmeyen her şey | `.claude/skills/model-dispatch/personas/general.md` |
| `ops` | Sonnet 5 | tam (bypassPermissions) + SADECE `ssh-mcp` (2026-07-17'den beri `--strict-mcp-config --mcp-config mcp-ssh-only.json` ile scoped — diğer roller gibi MCP'siz değil, ama diğer hiçbir MCP server'a da erişemiyor) — **teknik olarak sadece git commit/push/rm-rf engelli, SSH komut içeriği filtrelenmiyor, davranışsal kural (persona.md) dışında teknik zorlama yok** | canlı jump-server/kubectl teşhis + düzeltme; repo dosyalarına dokunmaz | `.claude/skills/model-dispatch/personas/ops.md` |
| `research` | Haiku 4.5 | salt-okunur (`Read,Grep,Glob` — Edit/Write/Bash yok, teknik olarak yazamaz) | tüm repo — tarama/arama/envanter işleri, ucuz model yeterli | `.claude/skills/model-dispatch/personas/research.md` |
| `judge` | Opus 4.8 | salt-okunur (`Read,Grep,Glob`) | karar-tek işleri — kod yazmaz, taramaz; prompt'ta tüm bağlam verilir, sadece düşünüp karar döner | `.claude/skills/model-dispatch/personas/judge.md` |

**research/judge için ikinci bir motor daha var — `dispatch-agy.sh` (Google
Antigravity CLI, ayrı kota havuzu) ÖNCELİKLİ tercih edilmeli, aşağıdaki "agy
engine" bölümüne bak.** Aynı motorda artık tek bir catch-all writer rolü de
var — `coder` (2026-09-01) — ama backend/design/sdk/general/ops'un ayrı ayrı
agy karşılığı YOK, hepsi hâlâ sadece `dispatch.sh`/Claude üzerinden çalışır;
`coder` bu beşinin hiçbirinin yerini almaz, sadece Claude kotası doluyken ya
da bağımsız bir ikinci-model denemesi istendiğinde ek bir seçenektir.

Model/tool eşleşmesi `dispatch.sh`'ta `ROLE_MODEL`/`ROLE_READONLY` associative
array'lerinde tanımlı. Yeni bir rol eklemek için `.claude/skills/model-dispatch/personas/<rol>.md`
oluştur + bu iki array'e ekle, aynı kalıbı kullan (kapsam sınırı + kısıt
listesi + gorev-loop doc-sync talimatı — jenerik "sen uzmansın" süsü yazma,
bkz. "Persona felsefesi").

## agy engine — Google Antigravity CLI (research/judge, ÖNCELİKLİ motor, 2026-08-27)

`dispatch.sh` DIŞINDA ikinci bir dispatch motoru var:
`dispatch-agy.sh <research|judge> <task-id> <prompt-file> [timeout-min] [model]`
— Google Antigravity CLI (`agy`) üzerinden çalışır, kullanıcının Google AI Pro
aboneliğine bağlı, **Claude hesaplarından (ambient/akb34/deepseek) tamamen
bağımsız ayrı bir kota havuzu**.

**Öncelik sırası, kullanıcı kararı (2026-08-27): research/judge işlerinde
ÖNCE agy denenir, Claude hesapları (ambient/akb34/deepseek) SONRA.** Gerekçe:
agy'nin kotası bu üç Claude hesabına göre çok daha geniş — research/judge
yükünü oraya kaydırmak Claude kotasını writer rollere (backend/design/sdk/
general/ops, hâlâ SADECE `dispatch.sh` üzerinden, agy'de yok) saklar. agy
başarısız olursa (hata, zayıf/eksik cevap) `dispatch.sh research|judge`'a
düş — sıra bu, tersi değil.

**Neden ayrı script, `dispatch.sh`'a gömülmedi:** agy'nin CLI şekli kökten
farklı, hepsi canlı `agy --help`/`agy mcp --help`/`agy models` + gerçek
çağrılarla doğrulandı (web dokümantasyonu bu araştırmada en az bir yerde
yanlış çıktı — `--mcp-config` diye bir flag YOK, gerçek help'te de yok):
- `--tools`/`--disallowedTools` yok — Read/Grep/Glob'a Claude'daki gibi
  yapısal (tool hiç mevcut değil) kısıtlama imkanı yok.
- Per-task `--mcp-config` yok — sadece kalıcı, paylaşımlı `agy mcp add
  <isim> <komut>` kaydı; Claude'daki gibi task-başına izole config dosyası
  veremiyorsun.
- `--max-budget-usd` yok, kota-sorgu subcommand'ı yok (`agy --help`/
  `agy changelog` ikisinde de yok, sadece per-session maliyet gösterimi var).
- `--model` tiered isimlerle geliyor (`gemini-3.5-flash-medium` gibi) ve
  `--effort` ile ÇAKIŞIYOR — ikisi birlikte verilince hata (canlı test
  edildi: `--model gemini-3.5-flash-medium --effort low` → "conflicts with
  --effort=low"). Bu yüzden script SADECE `--model` geçiyor, `--effort` hiç
  kullanmıyor.

Bu farklar `dispatch.sh`'ın mimarisine (worktree/budget-clamp/quota-precheck/
bridge-mcp) hiç uymadığı için ayrı script daha temiz — tek script'e "if
engine=agy" dallanması eklemek yerine.

**Güvenlik — tool-allowlist yokluğu böyle telafi edildi:**
`--dangerously-skip-permissions` bu script'te HİÇ verilmiyor, sabit — caller
kapatamaz. Canlı test edildi (2026-08-27): flag verilmeden bir yazma-tool
çağrısı headless modda otomatik reddediliyor (boş `response`, dosya hiç
oluşmuyor), salt-okuma (Read) ise sorunsuz çalışıyor (agy'nin kendi
changelog'una göre workspace-scoped read otomatik izinli, onaya gerek
duymuyor). Sonuç Claude'un allowlist'iyle AYNI değil ama pratik etkisi
örtüşüyor — allowlist'te tool hiç yok, agy'de tool var ama izin daima
reddediliyor (fail-closed). research/judge dışındaki (yazan) rollerin agy'ye
henüz eklenmemesinin asıl nedeni bu — yazma gerektiren bir işte fail-closed
davranış işe yaramaz, allowlist gerekir ki burada yok.

**`--new-project` ZORUNLU, script'te atlanamaz:** canlı test edildi
(2026-08-27) — `--add-dir` TEK BAŞINA yetmiyor, agy stale bir ÖNCEKİ proje
context'inden yanlış dosya okuyabiliyor (cross-project veri karışması —
bu repo'nun CLAUDE.md'sinde canlı SSH şifresi olduğu için ciddi risk).
Reprodüksiyon: `--add-dir .` ile alakasız eski bir projenin CLAUDE.md'sini
okudu; `--new-project` eklenince doğru dosyayı okudu. Script her çağrıda
otomatik ekliyor, opsiyonel değil.

**Model varsayılanları** (`dispatch-agy.sh`'ta `ROLE_MODEL`):

| Rol | Model | Gerekçe |
|---|---|---|
| `research` | `gemini-3.7-flash-medium` | ucuz/hızlı tarama, Claude'daki Haiku eşleniği |
| `judge` | `gemini-3.1-pro-high` | Google'ın en güçlü akıl yürütme kademesi — asıl amaç Claude'u farklı bir vendor'la çapraz doğrulamak, Claude'u agy üzerinden tekrar çalıştırmak değil (agy `claude-sonnet-4-6`/`claude-opus-4-6-thinking` de sunuyor ama bu amaç için anlamsız) |
| `coder` | `gemini-3.1-pro-high` | gerçek kod değişikliği, tarama değil — aynı gerekçeyle Gemini'nin en güçlü kademesi; agy'nin `claude-sonnet-4-6` seçeneği de var, isteyen görev için 5. argümanla override edilebilir (ör. aynı modeli iki farklı runtime'da karşılaştırmak) |

5. argümanla override edilebilir. `agy models` canlı komutu (2026-09-01) doğrulanmış tam liste: `gemini-3.7-flash-{high,medium,low}`, `gemini-3.6-flash-{high,medium,low}`, `gemini-3.1-pro-{high,low}`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`.

## agy `coder` rolü — yazan tek rol, worktree izolasyonu (2026-09-01)

`research`/`judge`'ın aksine `coder` dosya YAZAR — agy'nin Claude'daki gibi
`--tools`/`--disallowedTools` allowlist/denylist mekanizması YOK, o yüzden
farklı bir güvenlik modeli kullanıyor, tek başına iki katman:

1. **`--sandbox`** — agy'nin kendi terminal/dosya-yolu sandbox'ı. Canlı
   `agy changelog`'da doğrulandı: ".git added to core list of dangerous
   paths, preventing unauthorized or destructive repository modification"
   + genel komut/yol kısıtları. **Dürüst uyarı:** bu vendor'ın kendi
   changelog'unda YAZIYOR ama bu repoda uçtan uca canlı doğrulanmadı — 2026-09-01'de
   başlatılan bir test (`--sandbox --dangerously-skip-permissions` ile
   gerçekten `git commit`i engelliyor mu) sonuçlanmadan kesildi. `ops.md`'nin
   SSH uyarısıyla ve `dispatch.sh`'ın kendi commit/push denylist uyarısıyla
   aynı disiplin: bu flag'e güvenme, asıl güvence hâlâ worktree izolasyonu +
   apply.sh'tan önceki diff review.
2. **`dispatch.sh` ile AYNI worktree/branch adlandırması**
   (`$REPO_ROOT/.worktrees/$TASK`, branch `agent/$TASK`) — kasıtlı, böylece
   `diff.sh`/`apply.sh`/`verify.sh`/`cleanup.sh` bir agy-coder task için
   HİÇ değişmeden çalışıyor, tıpkı bir `dispatch.sh backend/design/sdk/
   general` task'ı gibi. Bedel: aynı task-id'yi iki motora AYNI ANDA
   dispatch edersen ikinci `git worktree add` yüksek sesle patlar (sessiz
   bozulma değil) — bir task-id'yi iki motorda paralel kullanma.

`--dangerously-skip-permissions` coder için ZORUNLU (yoksa her yazma
tool-call'u headless modda otomatik reddediliyor, 2026-08-27'de canlı
doğrulandı) — sadece worktree + `--sandbox` arada duruyor, başka teknik
engel yok. Persona (`personas/agy-coder.md`) commit/push/silme'yi davranışsal
olarak da yasaklıyor, Claude writer rollerindeki aynı çift-katman disiplin.

**Bridge YOK burada da** — `coder`'ın final raporu `submit_result` değil,
`personas/agy-coder.md`'nin zorunlu tuttuğu düz metin
`STATUS/CHANGED/RISK/VERIFIED/FINDINGS` formatı, `$TASK.agy.json`'ın
`response` alanında. Orkestratör bunu okuyup normal akışa döner:
`diff.sh $TASK` → incele → `apply.sh $TASK` → kullanıcıya rapor → onayla
commit.

**Budget clamp / kota kontrolü YOK** (script geneli için zaten belirtildiği
gibi) — bir coder task'ı döngüye girerse tek fren `--print-timeout`, `resume.sh`'ın
daralan-clamp/exit-19 mantığının agy tarafında karşılığı yok.

**Kullanım:**
```bash
bash .claude/skills/model-dispatch/scripts/dispatch-agy.sh coder KYC-999 .agent-logs/prompts/kyc-999.txt 20
```

**Bilerek hâlâ ERTELENEN:** backend/design/sdk/general/ops'un agy'de ayrı
karşılığı — `coder` bunların hepsini tek bir catch-all rolde topluyor (Claude
tarafındaki `general`'a en yakın), kapsam bölünmesi (backend vs design vs
sdk) agy tarafında yok. `sdks/` için `no-worktree` eşleniği de agy'de yok —
`coder` bir worktree içinde çalıştığı için `sdks/` (bu repoda gitignored,
ayrı iç-içe repo) worktree'de fiziksel olarak mevcut değil, dokunulamaz.

**Bridge/knowledge YOK:** `knowledge_write`/`submit_result`/`knowledge_search`
bu motorda BAĞLI DEĞİL — agy'nin per-task izole mcp-config'i olmadığı için
paylaşımlı kalıcı bir kayıt task-state karışması yaratırdı. Ajan bulgularını
düz metinle (`SUMMARY/COVERAGE/FINDINGS` ya da `VERDICT/REASONING/FINDINGS`
— bkz. `personas/agy-research.md`/`personas/agy-judge.md`) `$TASK.agy.json`'ın
`response` alanına yazar. **Orkestratör bunu okuyup durable bir bulgu varsa
`knowledge_write`'ı KENDİSİ çağırmalı** — bu otomatik değil, elle bir adım
(Claude tarafındaki `submit_result.findings[]`'in otomatik yazdığından
farklı).

**Foreground, worktree yok, budget-clamp yok, kota-precheck yok** — agy'de
bunların hiçbirinin API karşılığı yok (doğrulandı, tahmin değil). Script
`agy` bitene/`--print-timeout`'a çarpana kadar bloke eder, tek bir JSON blob
döner (Claude'un `stream-json`'ı gibi tur-tur akmıyor).

**Kullanım** (prompt formatı `dispatch.sh` ile AYNI — `# GOAL:` zorunlu satır):
```bash
bash .claude/skills/model-dispatch/scripts/dispatch-agy.sh research T-000350 .agent-logs/prompts/t-000350.txt
```

**Doğrulama (2026-08-27):** gerçek bir research görevinde (gateway
tenant-resolution 6-adım sırası) çalıştırıldı — doğru file:line'larla cevap
verdi, FINDINGS formatına uydu, hatta Claude'un daha önce bulduğu bir
incidental bulguyla (email-based login tenant discovery) bağımsız olarak
örtüşen yeni bir bulgu üretti — çapraz-model doğrulama sinyali, uydurma değil.

**Güncelleme (2026-09-01):** tek bir catch-all yazan rol eklendi — `coder`,
`--sandbox` + worktree izolasyonuyla (tool-allowlist yokluğu bu ikisiyle
telafi edildi, detay aşağıda "agy `coder` rolü" bölümünde). backend/design/
sdk/general/ops'un ayrı ayrı agy karşılığı hâlâ ERTELENMİŞ durumda — `coder`
hepsini tek rolde topluyor, kapsam bölünmesi yok.

## Çoklu hesap dağıtımı — `accounts.sh` (2026-08-02)

**Ortamda birden fazla Claude hesabı/login olabilir** — her biri kendi 5
saatlik/haftalık kotasına sahip ayrı bir `CLAUDE_CONFIG_DIR` (credentials +
session store). Şu an bilinen ikinci hesap: `akb34`
(`C:\Users\akbas\.claude-akb34` — interaktif kullanım için
`claude-akb34.bat` bunu başlatıyor). **Orkestratör (sen), tek bir hesabın
kotasına saplanıp kalmak yerine, paralel dispatch ederken bunu hesaba
katmalı** — bir hesap `quota_status: "high"` (≥%90) ise ve elde ikinci bir
hesap varsa, dispatch'i o hesaba yönlendirmek `ScheduleWakeup` ile
sıfırlanmayı beklemekten neredeyse her zaman daha iyi bir seçenek.

**Registry:** `.claude/skills/model-dispatch/scripts/accounts.sh`, tek
kaynak — `ACCOUNT_CONFIG_DIR` associative array'i (isim -> config dir) +
`resolve_account_config_dir <isim>` fonksiyonu. Yeni bir hesap eklemek için
SADECE bu dosyayı düzenle, başka hiçbir yeri değil — `dispatch.sh`,
`resume.sh`, `usage.sh`, `health.sh`, `context-usage.sh` hepsi bunu source
ediyor.

**3. hesap — `deepseek` (2026-08-03, deneysel/ucuz):** gerçek bir Claude
login DEĞİL — `claude-deepseek.bat`'ın kurduğu ortamla aynı, DeepSeek'in
Anthropic-uyumlu endpoint'ine (`api.deepseek.com/anthropic`) yönlendiriyor.
**Kullanıcı tarafından "daha ucuz ve deneysel" olarak işaretlendi** —
Sonnet/Opus/Haiku'ya eşdeğer kalite garantisi YOK, sadece aynı CLI
arayüzüyle çalışan ucuz bir alternatif; kalitenin maliyetten önemli olduğu
işlerde `akb34`/ambient tercih edilmeli, rutin/düşük-riskli dispatch
yükünü dağıtmak için `deepseek` kullanılmalı. `accounts.sh`'ta
`ACCOUNT_CONFIG_DIR` dışında altı `ACCOUNT_ANTHROPIC_*` associative array'i
daha var (`_BASE_URL`/`_AUTH_TOKEN`/`_MODEL`/`_OPUS_MODEL`/`_SONNET_MODEL`/
`_HAIKU_MODEL`) + `apply_account_extra_env <isim>` fonksiyonu —
`dispatch.sh`'ın arka plan subshell'inde `CLAUDE_CONFIG_DIR`'ın hemen
ardından çağrılıp bu env var'ları doğrudan export ediyor (akb34/ambient gibi
gerçek Claude hesaplarında hiçbir kayıt yok, no-op). Canlı doğrulandı
(2026-08-03): `dispatch.sh`'ın rol->model eşlemesi hâlâ `--model
sonnet|haiku|opus` alias'larını geçiyor, `ANTHROPIC_DEFAULT_SONNET_MODEL`
gibi env var'lar bu alias'ları deepseek'in gerçek model id'lerine
(`deepseek-v4-pro`/`deepseek-v4-flash`) resolve ediyor (yanıttaki
`modelUsage.canonicalModel` ile teyit edildi) — yani `dispatch.sh`'ın
`--model` mantığında hiçbir değişiklik gerekmedi. **Kota kontrolü bu hesap
için hep `"unknown"` döner (beklenen, bug değil):** `usage.sh` Anthropic'in
kendi OAuth `.credentials.json`'ını okuyor, deepseek hesabında öyle bir
dosya/kota kavramı yok (API key bazlı, per-token faturalama) —
`health.sh deepseek` bu yüzden hep `quota_status: "unknown"` + fail-open
exit 0 döner, `dispatch.sh` de "kota kontrol edilemedi, devam ediyorum"
uyarısıyla dispatch eder; bu normal, ScheduleWakeup'a gerek yok. Uçtan uca
gerçek bir `dispatch.sh research ... deepseek` çağrısıyla doğrulandı (repo
dosyası doğru okundu, rapor doğru döndü, maliyet ~$0.09/2 turn).

**`account` parametresi nerede var, nerede yok — kasıtlı seçim:** sadece
gerçekten `claude` çağıran ya da hesaba-özgü state (credentials, session
transcript) okuyan script'lere eklendi: `dispatch.sh` (8. arg), `usage.sh`,
`health.sh`, `context-usage.sh` (hepsinde son/opsiyonel arg). `resume.sh`
ise KENDİSİ bir `account` parametresi ALMAZ — orijinal dispatch'in hangi
hesabı kullandığını `$TASK.meta`'dan otomatik okuyup aynen tekrar kullanır
(aşağıya bkz., zorunlu — override edilemez). `status.sh`/`collect.sh`/
`diff.sh`/`apply.sh`/`verify.sh`/`wait.sh`/`list.sh`/`cleanup.sh`/
`cleanup-all.sh`/`new-id.sh` DEĞİŞMEDİ — bunlar sadece `.agent-logs/` ve
worktree dosyalarını işliyor, hangi Claude hesabının o task'ı çalıştırdığından
tamamen bağımsız; parametre eklemek burada süs olurdu (`list.sh` istisna:
görünürlük için her task'ın hangi hesapla dispatch edildiğini `$TASK.meta`'dan
okuyup ACCOUNT sütununda gösteriyor, salt-bilgi, davranışı değiştirmiyor).

**Varsayılan = ambient, geriye dönük uyumlu:** `account` argümanı boş
bırakılırsa hiçbir script `CLAUDE_CONFIG_DIR`'a dokunmaz — orkestratörün o an
zaten hangi hesap altında çalışıyorsa (ambient/inherited) o kullanılır, tam
olarak bu özellikten önceki davranış. `account` verilirse (`dispatch.sh
... "" 0 akb34` gibi) SADECE o dispatch'in arka planda çalışan `claude -p`
alt-süreci için, bir subshell içinde scoped olarak `CLAUDE_CONFIG_DIR`
override edilir — orkestratörün kendi ortamını ya da başka bir dispatch'i
etkilemez.

**Proaktif tercih — orkestratörün kendisi de ambient'i tüketir
(2026-08-03):** Yukarıdaki paragraf script'in mekanik davranışını anlatıyor
(`account` boşsa hiçbir şey değişmez) — orkestratörün account SEÇERKEN nasıl
karar vermesi gerektiği bundan ayrı bir katman. Orkestratörün kendi ana
oturumu da ambient hesabın kotasını tüketir — hem kendi reasoning'i hem de
(eğer dispatch'ler de ambient'e gidiyorsa) dağıtılan işler aynı havuzu
paylaşır, ambient kotası ikiye bölünüp daha hızlı biter, bu da orkestratörü
kendi işini yapamaz hale getirebilir. Kural: birden fazla hesap MEVCUTSA (şu
an bilinen: `akb34`, `deepseek` — bkz. yukarıdaki registry), dispatch
edilecek işler için VARSAYILAN tercih ambient DEĞİL, ikincil bir hesap
olmalı — öncelik sırası `akb34` (gerçek Claude hesabı, tam kalite) →
`deepseek` (ucuz/deneysel, rutin/düşük-riskli iş için — bkz. yukarıdaki "3.
hesap" notu). Ambient sadece şu üç durumda kullanılır: (a) başka hesap
yoksa, (b) diğer TÜM hesaplar da yüksek/tükenmişse, ya da (c) kullanıcı
açıkça ambient istediğinde. Pratikte: elde ikinci bir hesap varsa
`dispatch.sh`'ın 8. argümanını (account) boş BIRAKMA — `akb34` (ya da uygun
hesabı) açıkça geç; önce `health.sh akb34` ile o hesabın kotasına bak (adım
0'daki aynı kontrol), yüksek değilse oraya dispatch et. Bunu "Akış"
bölümündeki 0. adımın REAKTİF davranışıyla (bir hesap kota yüksekse başka
hesaba bak) karıştırma — bu paragraf PROAKTİF: kota henüz yüksek olmasa
bile, ambient'i orkestratörün kendi reasoning'i için tercihen BOŞ tut.

**Kota kontrolü hesap-bazlı:** `dispatch.sh`'ın dispatch-öncesi kota
kontrolü artık dispatch edilecek HEDEF hesabın kotasına bakıyor (kendi
ambient hesabına değil) — `usage.sh --raw <account>` ile. `health.sh
<account>` de aynı şekilde — bir batch dispatch etmeden önce hangi hesaba
gönderecekSEN o hesapla `health.sh` çalıştır, ambient'inkiyle değil.

**Resume, hesabı DEĞİŞTİREMEZ — mantıksal zorunluluk, keyfi kısıtlama
değil:** `claude --resume <session-id>`, o session'ı SADECE oluşturulduğu
`CLAUDE_CONFIG_DIR` altında bulabilir (session store hesaba özel). Bu yüzden
`dispatch.sh` her dispatch'te kullandığı hesabı (`account=` ismi VE
çözümlenmiş `config_dir=` yolu) `$TASK.meta`'ya yazıyor, `resume.sh` bunu
okuyup `DISPATCH_CONFIG_DIR_OVERRIDE` internal env var'ıyla (mevcut
`DISPATCH_RESUME`/`DISPATCH_SESSION_ID` deseniyle aynı kalıp)
`dispatch.sh`'a AYNEN geri veriyor — `dispatch.sh` bunu gördüğünde `account`
argümanını/registry lookup'ını tamamen atlayıp doğrudan bu değeri kullanır.
Gerçekten farklı bir hesapta yeniden denemek istiyorsan bu bir resume değil,
yeni bir task-id ile taze bir dispatch'tir.

**Önceden (bu özellikten önce) dispatch edilmiş task'lar:** `$TASK.meta`'da
`account=`/`config_dir=` satırı yok — `resume.sh` bunu boş okur, eskisi gibi
ambient ortamda devam eder (davranış değişmedi, kırılma yok).

**Bilinen pre-existing bug'lar, bu iş kapsamında düzeltildi (2026-08-02):**
`usage.sh` ve `context-usage.sh` daha önce ambient `CLAUDE_CONFIG_DIR`'ı
TAMAMEN yok sayıp hep sabit `~/.claude`'a bakıyordu — canlı doğrulandı: bu
orkestratör oturumunun kendisi `CLAUDE_CONFIG_DIR=...-akb34` ile
çalışırken bile `usage.sh` sessizce farklı (varsayılan `~/.claude`) bir
hesabın kotasını okuyordu, `context-usage.sh` ise kendi transcript'ini hiç
bulamıyordu (`~/.claude/projects` yerine gerçekte `...-akb34/projects`
altında). İkisi de artık önce ambient `CLAUDE_CONFIG_DIR`'a, sonra (verilmişse)
`account` argümanına bakıyor.

## Effort (reasoning) seviyesi

`claude -p`'nin `--effort <low|medium|high|xhigh|max>` flag'i var — 2026-07-17
öncesi `dispatch.sh` bunu HİÇ geçmiyordu (CLI'nin kendi varsayılanına
kalıyordu, elle ayarlanamıyordu). Artık `dispatch.sh`'ta `ROLE_EFFORT`
associative array'i var, rol bazlı varsayılan:

| Rol | Varsayılan effort | Gerekçe |
|---|---|---|
| `backend`/`design`/`sdk`/`ops` | `high` | gerçek kod/canlı teşhis, doğruluk önemli |
| `general` | `medium` | doküman/config düzenleme, düşük risk |
| `research` | `low` | Haiku zaten ucuz, salt-tarama iş — derin akıl yürütmeye gerek yok |
| `judge` | `high` | tek atımlık karar, keşif yok — kalite için ödemeye değer |

Varsayılanı ezmek için `dispatch.sh`'a 5. argüman geç:
```bash
dispatch.sh backend kyc-190 .agent-logs/prompts/kyc-190.txt 25 xhigh
```
Görev karmaşık/riskliyse (ör. çok dosyalı sync mantığı, race condition fix)
`xhigh`/`max`'a çık; basit tekrar-eden işlerde (dead-code silme, tek satır
fix) `medium`'a in — hız/maliyet kazancı, effort azaltmak doğruluğu
düşürmez sadece modelin ne kadar "düşündüğünü" ayarlar.

## Token tasarrufu (2026-07-17, judge-önerisi + orkestratör-ölçümü)

Bir judge task'ına "token/maliyet tasarrufu için ne yapılabilir" diye
sorulduğunda 8 öneri geldi; ikisi büyük etkiliydi, ama biri ÖLÇÜLMEDEN kabul
edilmeyip gerçek `claude -p` çağrılarıyla test edildi — sonuç kısmen
doğrulandı, kısmen düzeltildi. Disiplin: **judge'ın "büyük etki" dediği
tahminleri, ucuz bir gerçek ölçümle doğrulamadan mimariye gömme** — burada
tam olarak bu yapıldı ve tahminin bir kısmı yanlış çıktı.

**1. MCP şema kesme — ÖLÇÜLDÜ, KISMEN DOĞRU, uygulandı.**
Judge "Gmail/Calendar/Drive/context7/Playwright ~15-20K token" dedi — bu
ortamda o server'ların çoğu YOK (tek gerçek MCP server: `ssh-mcp`), yani
judge'ın spesifik listesi hatalıydı. Ama gerçek ölçüm (iki gerçek `claude -p`
çağrısı, `--strict-mcp-config` açık/kapalı, aynı diğer flag'ler) şunu
gösterdi:
- **Readonly roller (research/judge, `--tools "Read,Grep,Glob"` ile
  çalışıyor):** MCP şeması zaten context'e GİRMİYORDU —
  `cache_creation_input_tokens` fark ~3 token (gürültü). Judge'ın buradaki
  "büyük tasarruf" tahmini YANLIŞ.
- **Writer roller (backend/design/sdk/general/ops, `--tools` kısıtı YOK):**
  `cache_creation_input_tokens` 42180 → 26911, **~15.3K token/dispatch
  gerçek tasarruf**. Burada judge haklıydı.

Uygulama: `dispatch.sh` artık tüm rollere `--strict-mcp-config` geçiyor;
`ops` (tek gerçekten `ssh-mcp`'ye ihtiyacı olan rol) `--mcp-config
.claude/skills/model-dispatch/mcp-ssh-only.json` ile SADECE ssh-mcp'yi geri
alıyor — canlı test edildi (`ToolSearch "ssh"` 4 tool'u da buldu, diğer
hiçbir MCP tool'u yok). Diğer roller MCP'siz — zaten kullanmıyorlardı.

**2. Judge'a repo-tarama görevi verme — disiplin kuralı, kod değişikliği
yok.**
Judge Opus'ta ($15/M in, Sonnet'in 5×'i) ve persona'sı "keşfe ihtiyacın
olmamalı, prompt'ta her şey verilmeli" diyor — ama bu skill'in kendi
kendini denetleme turlarında (`max-turns-policy` $1.64, `dispatch-self-audit-judge`
$0.99) judge'a doğrudan "SKILL.md + tüm script'leri oku, karar ver"
denildi, yani PERSONA'nın kendi kuralı fiilen çiğnendi (script sorunu
değil, orkestratörün prompt yazma alışkanlığı sorunu). **Kural: judge'a
geniş bir okuma/keşif görevi verilecekse önce ucuz bir `research` (Haiku)
task'ı dispatch et, bulguları DAMITILMIŞ halde judge'ın prompt'una göm,
judge sadece karara odaklansın.** `.claude/skills/model-dispatch/personas/judge.md` zaten doğru
yazılmış (değiştirilmedi) — ihlal eden taraf hep orkestratörün prompt'uydu.

**Kapanan/reddedilen maddeler (judge'ın kendi kendini düzelttiği,
aksiyon gerekmiyor):** `stream-json --verbose` output token maliyetini
etkilemiyor (lokal log formatı, faturalanan şey modelin ürettiği metin) —
bu değiştirilmedi, zaten doğruydu. Persona tekrarı (~500 tok, cache'li)
önemsiz.

## Kaçak kota yakımı — bütçe clamp (2026-07-17, judge-tasarımlı)

Her dispatch'e `--max-budget-usd <tavan>` geçiliyor — döngüye giren/savrulan
bir task'ın 25dk boyunca kotayı yakıp `timeout` (exit 124) ile opak şekilde
bitmesine karşı bir fren. **Not:** ilk tasarım `--max-turns` (tur sayısı)
üzerineydi ama bu flag bu CLI sürümünde YOK — `claude -p --help`'te
doğrulandı, uydurma değil, gerçekten kontrol edildi. `--max-budget-usd` var
ve zaten asıl korktuğumuz şeyi (dolar bazlı kota tüketimi) doğrudan ölçüyor.

**Rol-bazlı seed tavan** (`dispatch.sh`'ta `ROLE_MAX_BUDGET_USD`), bu
oturumdaki gerçek `collect.sh` maliyetlerinin ~2.5-3 katı — n küçük (≤8
örnek), bunlar istatistik değil kasıtlı-gevşek backstop:

| Rol | Gözlenen max maliyet | Seed tavan |
|---|---|---|
| backend/general | $0.41 | backend $1.50, general $1.00 |
| design/sdk | $0.90 | design $2.50, sdk $2.00 |
| research | $0.18 | $0.50 |
| judge | $1.64 | $4.00 |
| ops | veri yok | $2.00 (seed) |

**İlerleme-farkında daralan clamp (`resume.sh` ile):** her dispatch
çağrısı `$TASK.attempt`'i artırır ve worktree'nin `git diff --numstat`
toplamı + yeni untracked dosyaların satır sayısını `$TASK.diffstat`'a
kaydeder (2026-07-26 fix: eskiden sadece `git diff --numstat` idi, tracked
dosya dışına kördü — bir task'ın TÜM ilerlemesi yeni dosya yazmaksa her
attempt "ilerleme yok" okunuyor, tavan kendi kendini sıfıra kilitliyordu tek
resume'da; `apply.sh`'nin zaten bildiği aynı untracked-körlüğü, aynı
`--untracked-files=all` çözümü). Attempt 1 → tam seed tavan. Attempt ≥2'de:
diff BİR ÖNCEKİ kayıttan büyümüşse (önceki koşu gerçekten ilerlemiş, sadece
yavaş kalmış) → yine tam seed tavan. İlerleme YOKSA (aynı diff, gerçek bir
döngü belirtisi) → attempt 2'de tavan %50'ye, attempt 3'te %25'e düşer;
attempt ≥4'te dispatch.sh dispatch'i TAMAMEN reddeder (**exit 19**) —
"insana devret, tekrar otomatik resume etme" diyerek. Read-only roller
(research/judge) worktree'siz çalıştığı için bu mantığa girmez, her zaman
düz seed tavan alır (zaten ucuz/kısa ömürlü). `no-worktree=1` ile dispatch
edilmiş yazan-rol task'lar da aynı düz-seed davranışına girer (bkz.
"no-worktree parametresi") — izole bir worktree diff'i olmadan "ilerleme
oldu mu" ölçülemez, bu yüzden halving/exit-19 refuse'u onlar için de devre
dışı. Bunun bedeli: no-worktree bir task gerçekten döngüye girerse (aynı
şeyi tekrar tekrar deniyorsa) bu clamp onu YAKALAMAZ — sadece kota
tavanı/timeout onu durdurur, halving'in erken uyarısı yok.

**Manuel override (`resume.sh <task> [timeout] [effort] [budget-usd]`):**
4. arg verilirse clamp mantığı TAMAMEN atlanır (halving da, exit 19
refusal de) — verilen tutar direkt `--max-budget-usd` olur. Bu bir insan
kararı içindir: clamp'in diffstat sinyali yanlış tetiklendiyse (ör. yukarıdaki
untracked-körlüğü gibi henüz bilinmeyen bir başka kör nokta), rutin
otomatik-resume değil. Fix'ten sonra bile clamp'in kör olabileceği başka
senaryolar (ör. ilerleme = dosya SİLME) teorik olarak açık — override bu yüzden
kaldı, sadece son çare.

**Bütçe tavanına gerçekten çarpma tespiti (status.sh):** `--max-budget-usd`
sınırına çarpınca CLI'nin tam olarak ne yazdığı bu ortamda henüz CANLI
gözlemlenmedi (smoke-test sadece flag'in KABUL edildiğini doğruladı, tavana
çarpmadı) — `status.sh`'taki `BUDGET_SIGNATURE` regex'i **doğrulanmamış,
best-effort** bir tahmin (`max.?budget|budget.*exceed|cost limit|spending
limit`). Gerçek bir çarpma gözlemlenirse regex'i gerçek metne göre düzelt,
tahmin üstüne tahmin yapma. Eşleşirse `status.sh` **exit 20**
("budget_capped") döner — `resume.sh` bunu da (17/14 gibi) resumable
sayar, yukarıdaki daralan-clamp mantığıyla otomatik devam eder.

`general` de `backend`/`design`/`sdk` gibi tam yazma yetkisiyle çalışır —
farkı sadece kapsamının repo-geneli olması (Dokumanlar/*.md, config, script,
diğer üçüne girmeyen dosyalar). Görev asıl backend/design/sdk kapsamına
giriyorsa `general` yerine o rolü kullan — `general` varsayılan değil, kalan
kategori.

`research` ve `judge` **worktree AÇMAZ** (2026-07-17'den beri) — Edit/Write/
Bash yapısal olarak yok, tek amaç izolasyon olduğu için worktree onlara sıfır
fayda + gereksiz disk/IO maliyeti getiriyordu (kendi-denetim'de judge'ın
bulduğu öneri — bkz. altta "kendi-denetim" notu). Doğrudan ana checkout'ta
(`REPO_ROOT`) çalışırlar. Yan fayda: bu sayede yukarıdaki "commit'lenmemiş
değişiklik görünmüyor" sınırlaması research/judge için GEÇERSİZ — ana
checkout'ta çalıştıkları için senin commit'lenmemiş değişikliklerini de
görürler. Sadece backend/design/sdk/general/ops (yazan roller) hâlâ ayrı
worktree'de çalışır ve o sınırlamaya tabidir.

## Exit code standardı

Her script bunlara uyar — çıktı metnini parse etmeye gerek yok, sadece exit code'a bak:

| Kod | Anlam |
|---|---|
| 0 | başarılı |
| 1 | genel hata (yanlış kullanım, eksik dosya, non-timeout task failure) |
| 10 | task hâlâ çalışıyor |
| 11 | task/worktree bulunamadı |
| 12 | dosya çakışması (dispatch reddedildi) |
| 13 | verify.sh en az bir dosyada FAIL buldu |
| 14 | task timeout'a uğradı |
| 15 | kota ONAYLANMIŞ ≥%90 (health.sh `quota_status: "high"`), dispatch reddedildi/önerilmedi — kota bilinmiyorsa (usage.sh arızalı/parse edilemedi, `quota_status: "unknown"`) health.sh artık exit 0 ile fail-open döner + stderr uyarısı, 15 DEMEZ (2026-07-30 fix, H6 — eskiden ikisi aynı koda düşüyordu, `ScheduleWakeup` matematiği `null` reset zamanı üstünden NaN üretiyordu) |
| 16 | apply.sh: patch uygulanamadı, repo değişmedi (all-or-nothing) |
| 17 | status.sh: kota RUN SIRASINDA (mid-run) tükendi — task bug'ı değil, ertele+tekrar dene |
| 18 | resume.sh: task resumable state'te değil (hâlâ çalışıyor ya da temiz bitmiş) |
| 19 | dispatch.sh: no-progress bütçe clamp tükendi, dispatch reddedildi — insana devret |
| 20 | status.sh: task kendi `--max-budget-usd` tavanına çarptı (best-effort tespit, bkz. "Kaçak kota yakımı") |

## Task ID — immutable

`task-id` olarak **ticket ID'sini kullan** (KYC-121, FE-135, birleşik batch için
FE-135-FE-136 gibi) — proje zaten bu ID'leri kalıcı kimlik olarak kullanıyor,
ayrı bir ID uzayı icat etme. Ticket'sız ad-hoc iş için `new-id.sh` bir
`T-000341` tarzı sıralı ID üretir. **Bir task'ı dispatch ettikten sonra ID'sini
değiştirme** — worktree/branch/log dosyaları hep bu string'e bağlı, isim
değişirse iz kaybedilir.

## Prompt formatı — tek hedef zorunlu

`dispatch.sh` artık prompt dosyasının `# GOAL: <tek cümle>` ile başlamasını
ZORUNLU tutuyor (yoksa exit 1, hiç dispatch etmez). Headless bir ajan geri
soru soramaz — belirsizlik varsa dispatch etmeden ÖNCE sen çöz (ya da
kullanıcıya sor), tek, net bir hedef yaz. Kötü: "Bug'ı çöz, testleri düzelt,
refactor yap, log ekle." İyi: "Prevent duplicate payment creation. Nothing
else." Opsiyonel `# FILES: yol1,yol2` başlığı otomatik çakışma reddini
etkinleştirir.

## Persona felsefesi

Persona dosyaları BİLEREK "sen 15 yıllık mühendissin, Clean Architecture
benimse" tarzı jenerik rol tanımı İÇERMİYOR — modelin zaten bildiği genel
yazılım bilgisini tekrarlamanın davranışı ölçülebilir şekilde değiştirdiğine
dair güçlü kanıt yok, üstelik her çağrıda token maliyeti yaratıyor. Bunun
yerine sadece PROJEYE ÖZGÜ, modelin önceden bilemeyeceği kısıtlar var:
kapsam sınırı (Forbidden listesi), var olan pattern'leri tekrar kullanma
talimatı, ve zorunlu kısa çıktı formatı (`STATUS/Changed/Risk/Verified`).
Yeni bir persona eklerken bu disiplini koru — süs değil, kısıt yaz.

**Orkestratör (sen) dispatch öncesi persona dosyasını OKUMAZ.** `dispatch.sh`
bunu otomatik yükleyip `--append-system-prompt`'a ekliyor — senin ayrıca
`Read .claude/skills/model-dispatch/personas/<rol>.md` yapman gereksiz context/token harcaması,
üstelik dosya sana zaten ne yazdığını söylemez (dispatch anında persona
otomatik ekleniyor, sen sadece rolü seçiyorsun). Yukarıdaki tablo hangi rolün
neyi kapsadığını söylemeye yeter — rol seçimi için bu tablo tek referans
olmalı. Persona dosyasını sadece PERSONANIN KENDİSİNİ değiştireceksen aç.

## Alt model ↔ orkestratör iletişim kanalı — agent-bridge MCP

Dispatch edilen ajan artık tamamen tek yönlü/kör değil — `.claude/skills/model-dispatch/mcp/bridge/agent-bridge.js` adlı sıfır-bağımlılık stdio MCP server iki şey sağlıyor:

- **`ask_orchestrator(question, timeout_seconds?)`** — alt model gerçekten belirsiz/riskli bir karar noktasında bloke-edici soru sorabilir (varsayılan 180s, tavan 600s bounded-poll; cevap gelmezse `NO_ANSWER_YET` sentinel'iyle döner, alt model kendi kararını verip devam eder — sonsuza kadar beklemez).
- **`submit_result(status, summary, changed_files?, risk?, verified?)`** — final rapor artık `collect.sh`'ın stream-json'dan kazıdığı serbest metin DEĞİL, yapılandırılmış veri. Orkestratör bunu `get_result(task_id)` ile id üzerinden sorgular.

Orkestratör tarafı: `list_pending_questions()`, `answer_question(task_id, answer)`, `get_result(task_id)` — proje-scope `.mcp.json` (repo kökü) ile SENİN oturumuna da bağlı, restart sonrası otomatik yüklenir. Alt model tarafı `task_id` parametresi vermeden çalışır (`DISPATCH_TASK_ID` env, `dispatch.sh`'ın subshell'inde export edilir).

Depo: `.agent-logs/<task>.bridge.json` — hiçbir taraf bunu doğrudan okumaz/yazmaz, hepsi tool call üzerinden konuşur (dosya sadece server'ın iç deposu). Eşzamanlı erişim exclusive-create lockfile + stale-lock kurtarma ile korunuyor, gerçek `Atomics.wait` ile CPU-spin'siz bloklu bekleme kullanılıyor. `agent-bridge.js` bu yolu KENDİ `__dirname`'inden hesaplıyor (`path.resolve(__dirname, '..','..','..','..')`) — yani "hangi repo" sorusu, o script'in dosya sisteminde FİİLEN nerede oturduğuna bağlı, env'e değil.

**Bu yüzden orkestratör tarafı (`.mcp.json`) ile alt-model tarafı (dispatch.sh'ın `--mcp-config`'i) AYNI repo'daki agent-bridge.js'i işaret etmek ZORUNDA — biri farklı bir repoya işaret ederse ikisi farklı `.agent-logs/` klasörüne yazar/okur, submit_result hiç görünmez.** Tam olarak bu oldu (2026-07-30 bulundu, H1): bu skill `MCpAndSkill/multiagent2`'den bu repoya kopyalanmıştı, ama hem kök `.mcp.json` hem de eski `mcp-bridge-only.json`/`settings-enforce-result.json` içindeki mutlak path hâlâ `multiagent2`'yi gösteriyordu — 27+ arvis-task'ının bridge state'i sessizce yanlış repoya (multiagent2'nin `.agent-logs/`'una) düşmüştü, `cleanup.sh` onları hiç görmüyordu. Düzeltme iki parça:
1. Kök `.mcp.json` bu repoyu (`arvis_code`) gösterecek şekilde düzeltildi.
2. `dispatch.sh` artık statik `mcp-bridge-only.json`/`settings-enforce-result.json` dosyalarını KULLANMIYOR — her dispatch'te `$SCRIPT_DIR`'den (her zaman doğru repoyu çözer, skill nereye kopyalanırsa kopyalansın) `$LOG_DIR/$TASK.mcp-bridge.json` + `$TASK.settings.json` taze üretiyor. İki statik dosya hâlâ diskte duruyor (referans/manuel test için, path'leri de düzeltildi) ama dispatch akışında artık okunmuyorlar.

**Skill'i üçüncü bir repoya kopyalarsan**: kök `.mcp.json`'ı YENİ repodaki `agent-bridge.js`'e elle güncelle (dispatch.sh tarafı otomatik doğru çözer, orkestratör tarafı çözmez) — sonra oturumu restart et.

Şu an SADECE writer rollere (backend/design/sdk/general/ops) bağlı — `mcp-bridge-only.json` ile `--mcp-config`'e ekleniyor (ops için `mcp-ssh-only.json` ile birlikte, aynı `--mcp-config` çağrısında iki dosya). Readonly roller (research/judge) dışarıda — Edit/Write/Bash zaten yok, persona'ları "keşfe/geri-soruya ihtiyacın olmamalı" diyor, ekstra kanalın şu an net faydası yok.

### Paylaşımlı ajan bilgisi — knowledge_write / knowledge_search (2026-08-23)

`submit_result`'a opsiyonel `findings[]` alanı eklendi — bir ajanın turu
sırasında öğrendiği, gelecekteki başka bir dispatch'in yeniden keşfetmesi
yerine sorgulayabileceği kalıcı bilgiyi kaydeder. **Ayrı bir çağrı gerekmez**
— Stop-hook'la zaten zorunlu olan `submit_result`'ın içinde gelir, agent-bridge
her finding'i otomatik olarak knowledge DB'ye yazar. `knowledge_write` de
tool listesinde var (nadir, turu bitirmeden ARA bir kaydın gerektiği durumlar
için) — asıl yol `findings[]`.

**`ROLE_BRIDGE` — `ROLE_READONLY`'den ayrıştırıldı:** eskiden bridge erişimi
(`ask_orchestrator`/`submit_result`) sadece yazan rollere bağlıydı, research/
judge dışarıdaydı — bilgi üretiminin en çok ihtiyaç duyduğu iki rol (research
tarar, judge çelişki çözer) sistemin dışındaydı. Artık tüm 7 rol bridge'e
bağlı; research/judge dosya erişimi hâlâ salt-okunur (Read/Grep/Glob) ama
`--tools` allowlist'ine bridge tool isimleri (`mcp__agent-bridge__*`)
explicit eklendi — MCP server bağlı olsa bile allowlist'te adı geçmeyen bir
tool'a erişilemiyor, writer rollerin denylist modeliyle karışmasın diye.

**Şema** (`.claude/skills/model-dispatch/mcp/knowledge-store.js`, SQLite —
`node:sqlite`, deneysel ama Node 24'te FTS5 dahil çalıştığı doğrulandı):
- `topic` yazma anında normalize edilir (lowercase, boşluk/`_` → `-`) —
  "auto_threshold"/"auto-threshold" aynı kovaya düşer.
- `category` 5 değerle sabit: `behavior|architecture|constraint|bug|decision`.
- `evidence[].dirty` **sunucu tarafında** hesaplanır (`git status --porcelain`)
  — ajan beyanına güvenilmez. research/judge worktree açmadan ana checkout'ta
  çalıştığı için (bkz. yukarısı) commit'lenmemiş koda işaret eden kanıt asla
  sessizce "temiz" görünmemeli.
- `confidence` float YOK — `status` lifecycle (`candidate|verified|stale|
  superseded|promoted`) + `verification_count` kullanılır. `promoted` sadece
  ana oturumun Dokumanlar'a MANUEL terfi kararını işaretler — **otomatik
  senkron yok**, knowledge insan dokümantasyonundan bağımsız bir ajan-bilgisi
  sistemi (kararlaştırıldı: Dokumanlar = insan için kalıcı karar, knowledge =
  ajanlar için ara/kalıcı olabilir olgu).
- `knowledge_search` her sonucu okuma anında `git log <commit_sha>..HEAD --
  <evidence-dosyaları>` ile freshness kontrolünden geçirir — boşsa taze,
  doluysa `stale_warning` ile işaretlenir. Ayrı bir auditor beklemeden,
  modelsiz, deterministik.

**Arama:** BM25 (FTS5) + cosine (embedding varsa) hibrit, RRF (reciprocal
rank fusion) ile birleştirilir. Embedding yoksa (Ollama kapalı/erişilemez)
sadece BM25 ile devam eder — arama asla çökmez, sadece anlamsal katmanı
kaybeder.

**Embedding — `ollama-embed.js` + `ollama-watchdog.js`:** model `bge-m3`
(1024d, çok dilli — Türkçe claim + İngilizce kod tanımlayıcıları köprüsü
için seçildi), Ollama üzerinden. Donanımda ölçüldü (GTX 1650 Ti, 4GB VRAM):
`num_gpu:999` (tüm katmanları GPU'ya zorla) + `num_ctx:4096` (varsayılan
context OOM veriyordu — kök neden context buffer boyutuydu, GPU'nun kendisi
değil; 4096 gerçek finding boyutlarının ~10 katı pay verirken VRAM'in
yarısından azını kullanıyor — 8192 native max kartın %95'ini yer, kalite
katkısı yok). Python+torch alternatifi ölçülüp reddedildi (`import torch`
tek başına ~10sn — sıcak Ollama'nın ~450ms'sinin ~20 katı, + ikinci runtime
bağımlılığı).

Kullanıcı Ollama'nın sürekli açık kalmasını istemedi — bridge kendi
yönetiyor: `knowledge_write`/`search` çağrısı `localhost:11434`'ü kontrol
eder, kapalıysa `ollama serve`'i detached spawn eder (agent-bridge.js'in
kendi ömründen — per-dispatch, ~25dk — bağımsız yaşasın diye `unref()`).
İlk spawn'da ayrıca `ollama-watchdog.js`'i (idempotent, pidfile ile
tekilleştirilmiş) detached başlatır — bu, TÜM dispatch'ler arasındaki idle
süresini (`.claude/knowledge/.ollama-last-used` dosyasından) izleyip 15dk
hiç çağrı gelmezse `taskkill /IM ollama.exe` ile kapatır. Tek bir
agent-bridge.js instance'ı bunu yapamaz (kendisi task'ın ömrüyle birlikte
ölür) — watchdog bu yüzden ayrı, uzun ömürlü bir process.

**Fail-soft, uçtan uca:** Ollama spawn edilemezse/embed isteği başarısız
olursa `embed()` `null` döner, İSTİSNA FIRLATMAZ — kayıt embedding'siz
(BM25-only) yazılır, dispatch akışı asla bloklanmaz.

**Doğrulama (2026-08-23, gerçek MCP round-trip + gerçek Ollama):**
`knowledge-store.js` izole test edildi (normalize, kategori validasyonu,
dirty:true/false her ikisi de gerçek git durumuyla doğrulandı, FTS5 arama).
Tam MCP stdio protokolü (`initialize`→`tools/list`→`tools/call`) gerçek bir
child process üzerinden koşturuldu: `submit_result` findings[] ile gerçek
bir knowledge kaydı yazdı, embedding gerçekten Ollama'dan geldi (SQLite'ta
4096 byte = 1024×float32 doğrulandı), `knowledge_search` MCP üzerinden aynı
kaydı buldu. Eski tool'lar (`ask_orchestrator`/`list_pending_questions`)
sync→async wrapper refactor'ından sonra da bozulmadan çalıştı.

**Bilerek ERTELENEN (kod yazılmadı, sırası gelince yapılacak):**
- `memory-auditor` rolü — ~50+ gerçek kayıt birikene kadar denetleyecek
  hiçbir şey yok, şimdi yazmak boş iş.
- research→backend benchmark (knowledge'lı/knowledge'sız tool-call/maliyet
  farkı) — gerçek kullanım verisi birikmeden anlamlı değil.
Bu iki madde SKILL.md'nin kendi "ölçmeden mimariye gömme" kuralına uyar —
tahmin üstüne inşa etmiyoruz.

### Zorunlu final rapor — Stop hook (`enforce-submit-result.js`)

Writer rollere `--settings settings-enforce-result.json` geçiliyor (proje/kullanıcı settings'ini REPLACE etmez, sadece ekler) — bu, bir `Stop` hook kaydediyor: alt model turu bitirmeye çalıştığında `submit_result` çağrılmamışsa hook'u çalıştırıp devam etmeye zorluyor.

**Ölçülmüş, kritik bulgu (2026-07-21):** Stop hook'ta "durmayı engelle" için İKİ farklı protokol var, biri BU CLI'nin `-p` (headless/print) modunda ÇALIŞMIYOR:
- `exit 2` + stderr mesajı (birçok dokümantasyonda "blocking" için standart yol) — **canlı test edildi, İŞE YARAMADI**: hook çalıştı (sayaç dosyası kanıtlıyor), ama session yine de tek turda durdu, `stop-hook-error` bildirimiyle sonuçlandı. Headless print modunda bu protokol sessizce görmezden geliniyor gibi.
- `stdout`'a `{"decision":"block","reason":"..."}` JSON'ı + `exit 0` — **canlı test edildi, ÇALIŞTI**: alt model bloklanıp gerçekten `submit_result`'ı çağırmaya zorlandı (1 turn yerine 4 turn, doğrulanan gerçek `claude -p` dispatch'i ile). `enforce-submit-result.js` bu yüzden JSON-decision yolunu kullanıyor, exit-2 DEĞİL — tahmin değil, iki ayrı canlı test ile karşılaştırmalı doğrulandı (aynı disiplin: SKILL.md "Token tasarrufu" bölümündeki "ölçülmeden mimariye gömme" kuralı).

**Sonsuz döngü freni:** `enforce-submit-result.js` kendi deneme sayacını (`$TASK.stophook-count`) tutar, `MAX_BLOCKS=3` sonrası pes edip durmaya izin verir + `$TASK.result-missing` işareti bırakır (budget-clamp'taki aynı ruh — insan/orkestratör fark etsin, sonsuza kadar zorlamaya devam etme).

### Doğrulama kaydı (2026-07-21, canlı `claude -p` dispatch'leriyle)

- Sentetik MCP client testi: 9/9 geçti (protokol, round-trip, timeout sentinel, 10 eşzamanlı `submit_result` yazımı — dosya bozulmadı).
- Gerçek dispatch (general rol, bridge ile): alt model `ask_orchestrator` çağırdı → orkestratör (ben) gerçek `answer_question` MCP tool'uyla cevapladı → alt model cevabı aldı → `submit_result` → orkestratör `get_result(task_id)` ile id'yle sorguladı, tutarlı geldi. İki kez tekrarlandı (bir kez manuel script client'la restart öncesi, bir kez SESSİON RESTART sonrası orkestratörün KENDİ proje-scope MCP tool'larıyla) — ikisi de geçti.
- Stop hook: submit_result çağırmadan bitirmeye çalışan adversarial prompt → hook 3 kez bloklayana kadar zorladı (ya da bu testte 1 kez bloklayıp model uydu) → alt model `submit_result`'ı çağırdı, tam istenen içerikle.

## Script envanteri

| Script | Ne yapar |
|---|---|
| `health.sh [account]` | Ön-uçuş kontrolü — JSON döner (`account`/`git`/`worktree`/`claude_cli`/`disk_space`/`quota_ok`/`quota_status`). `account` verilmezse ambient hesap kontrol edilir; verilmişse (`accounts.sh` registry'sinden bir isim) O hesabın kotası kontrol edilir — dispatch edeceğin hesapla aynısını ver. Kota ONAYLANMIŞ ≥%90 (`quota_status: "high"`) ise exit 15; kota kontrol EDİLEMEDİYSE (`"unknown"`) artık exit 0 ile fail-open döner, eskiden ikisi de aynı exit 15'e düşüyordu (H6). Bilinmeyen hesap ismi: exit 1. Dispatch'ten ÖNCE çalıştır. |
| `usage.sh [--raw] [account]` | Kota durumu (5 saatlik/haftalık %, sıfırlanma zamanı). `--raw` ham JSON döner (health.sh/dispatch.sh bunu kullanır). `account` verilmezse ambient `CLAUDE_CONFIG_DIR` (2026-08-02 fix — eskiden bunu tamamen yok sayıp hep `~/.claude`'a bakıyordu), verilmişse `accounts.sh` registry'sinden o hesabın kotasına bakar. |
| `new-id.sh` | Ticket'sız ad-hoc işler için `T-000341` tarzı sıralı immutable ID üretir. Ticket'lı iş için gerekmez, ticket ID'sini kullan. |
| `dispatch-agy.sh <research\|judge> <task-id> <prompt-file> [timeout-min] [model]` | İkinci motor (Google Antigravity CLI, `agy`) — SADECE research/judge, ÖNCELİKLİ tercih (ayrı/geniş kota havuzu, bkz. "agy engine" bölümü). Worktree/budget-clamp/kota-precheck/bridge yok — foreground çalışır, `$TASK.agy.json`'a tek JSON blob yazar. |
| `dispatch.sh <role> <task-id> <prompt-file> [timeout-min] [effort] [budget-usd] [no-worktree] [account]` | Kota kontrolü + `# GOAL:` zorunluluğu + (varsa) `# FILES:` çakışma kontrolü yapar, sonra worktree açar, headless `claude -p`'yi arka planda başlatır. Varsayılan timeout 25dk. 7. arg `no-worktree=1` verilirse worktree AÇMAZ, ana checkout'ta (`REPO_ROOT`) direkt çalışır — bkz. "no-worktree parametresi" bölümü. 8. arg `account` verilirse (bkz. "Çoklu hesap dağıtımı") o hesabın kotası kontrol edilir ve `claude -p` alt-süreci o hesabın `CLAUDE_CONFIG_DIR`'ı altında çalışır; boşsa ambient hesap (eski davranış, değişmedi). Bilinmeyen hesap ismi: exit 1, hiçbir şey başlatılmaz. |
| `list.sh` | Bilinen TÜM dispatch'leri (running/done/timeout/quota_out/budget_capped/failed) listeler — hiçbir iş unutulmasın diye. `status.sh`'ı her task için tekrar kullanır (2026-07-30 fix, H7 — eskiden kendi exitcode/.err parse'ını yapıyordu ve `budget_capped`'i (exit 20) tanımıyordu, `status.sh` ile çelişen bir "failed(N)" gösteriyordu). ACCOUNT sütunu her task'ın hangi hesapla dispatch edildiğini `$TASK.meta`'dan gösterir (salt-bilgi). |
| `status.sh <task-id>` | Tek bir task'ın durumu (exit code'a bak). |
| `collect.sh <task-id>` | Ajanın yazdığı özet raporu + maliyetini (`total_cost_usd`) yazdırır. Log formatı `stream-json` (2026-07-14'ten beri) — task kill edilir/timeout'a uğrarsa (`--output-format json`'ın aksine) o ana kadarki turlar KAYBOLMAZ, `collect.sh` "PARTIAL" olarak son event'i raporlar. |
| `diff.sh <task-id>` | Worktree'deki değişikliği gösterir (salt-okunur). `no-worktree=1` ile dispatch edilmiş bir task için worktree yoktur — bunu tespit edip (`$TASK.meta`'dan) "zaten diskte, doğrudan `git -C <yol> status/diff` ile bak" mesajıyla exit 0 döner. |
| `apply.sh <task-id>` | Değişikliği ana checkout'a kopyalar — stage/commit YAPMAZ. `no-worktree=1` task'larda kopyalanacak ayrı bir worktree kopyası yok — no-op, exit 0. |
| `verify.sh` | Ana checkout'taki TÜM commit'lenmemiş dosyaları (herhangi bir kaynaktan — apply.sh, elle düzenleme, fark etmez) tarar, `.js` dosyalarına `node --check` (backend) ya da `esbuild --loader:.js=jsx` (`portals/` altı) uygular, PASS/FAIL raporu verir. |
| `resume.sh <task-id> [timeout-min] [effort] [budget-usd]` | Kota (exit 17) ya da timeout (exit 14) yüzünden yarım kalan bir task'ı AYNI role/worktree ve `claude --resume <session-id>` ile GERÇEK konuşmayı devam ettirerek yeniden dispatch eder — model önceki turlardaki akıl yürütmeyi/ne yaptığını hatırlar, sadece dosya durumuna bakıp tahmin etmez. Sadece exit 17/14/20 durumunda çalışır, başka state'te reddeder (exit 18). Task'ın `no_worktree` modunu `$TASK.meta`'dan okuyup aynen `dispatch.sh`'a geçirir — no-worktree başlayan bir task resume'da da no-worktree kalır. Aynı şekilde `account`/`config_dir`'ı da `$TASK.meta`'dan okuyup ZORUNLU olarak aynen geçirir (bkz. "Çoklu hesap dağıtımı") — bunun kendi `account` parametresi YOKTUR, override edilemez. |
| `wait.sh <task-id> [task-id2 ...]` | Verilen task(lar) bitene kadar `status.sh`'ı polling ile BLOKE EDER. `dispatch.sh` anında döndüğü için tek başına "bitince haber ver" sağlamaz — bunu Bash tool'una `run_in_background:true` ile verirsen harness GERÇEKTEN bitince bildirim üretir. |
| `wait-quota.sh [account] [max_utilization_pct] [poll_seconds]` | Kota `max_utilization_pct`'in (varsayılan %90) ALTINA düşene kadar `usage.sh --raw`'ı polling ile BLOKE EDER (varsayılan 60sn aralık). `health.sh`/`dispatch.sh` kota ≥%90 diye reddettiğinde, kör bir `ScheduleWakeup` süresi tahmin etmek yerine bunu kullan. Her poll'da beş-puanlık bandı (`floor(util/5)*5`) bir öncekiyle karşılaştırır — band değiştiyse (yani kota her %5 arttıysa) bir satır yazdırır, değişmediyse SESSİZ kalır. Bash tool'una `run_in_background:true` ile ver, sonra `Monitor` tool'uyla izle — her yazdırılan satır (yani her %5 kota artışı) ayrı bir bildirim olarak gelir, "bitene kadar tek sessiz blok" değil canlı bir damla akışı sağlar. Kota %90'ın altına inince exit 0 ile biter. `usage.sh` arızalanırsa (ağ/credential/bilinmeyen hesap) exit 1 — kota durumunu tahmin etmez, durur. Kullanım amacı: dispatch GATE'i (belirli hesabın kotası açılana kadar bekle). |
| `quota-watch.sh [account] [poll_seconds]` | `wait-quota.sh`'tan FARKLI amaç: bloklayıp beklemez, hiç exit ETMEZ (8 saatlik güvenlik tavanı hariç) — orkestratörün KENDİ (genelde ambient) kotasını session boyunca arka planda izler, her %5 bandı değiştiğinde (yukarı ya da aşağı) bir satır yazdırır (varsayılan 5dk poll). Bash tool'una `run_in_background:true` ile başlat, `Monitor` tool'uyla izle — SKILL.md'nin altındaki "Session Hygiene — Kota Kontrolü" bölümündeki elle ~15-20dk'da bir `usage.sh` çalıştırma talimatını otomatikleştirir. `usage.sh` arızalanırsa exit 0 ile durur (log'da neden yazar) — sonsuza kadar hata basmaz. |
| `cleanup.sh <task-id>` | Worktree+branch+TÜM `.agent-logs/<task-id>.*` artıklarını (meta/files/prompt.orig/prev-arşivler dahil) siler. DESTRUCTIVE — kullanıcı onayı olmadan çağırma. |
| `cleanup-all.sh [--yes] <task-id>... \| --applied [--yes]` | `cleanup.sh`'ın toplu hali — tek tek çağırma yerine bir seferde. `--yes` olmadan sadece ne sileceğini listeler (dry-run, hiçbir şeye dokunmaz — TTY olmayan headless Bash'te `read` onayı çalışmaz, onayı SEN kullanıcıdan alıp `--yes` ile geçersin). `--applied`: worktree'sinde artık commit'lenmemiş diff kalmamış (apply.sh'ın çıkardığı) TÜM task'ları otomatik hedefler. |
| `context-usage.sh <session-id> [max-tokens] [account]` | Bu ana oturumun context penceresi doluluk yüzdesi. `account` verilmezse ambient `CLAUDE_CONFIG_DIR` altında arar (2026-08-02 fix — eskiden hep `~/.claude/projects`'e bakıyordu, ambient farklıysa transcript'i hiç bulamıyordu). |

## Akış

**research/judge dispatch edecekse önce bunu oku:** kota kontrolünden ÖNCE,
işi `dispatch-agy.sh`'a (agy engine — ayrı/geniş kota havuzu) yönlendirmeyi
düşün, sadece Claude hesaplarına değil — bkz. yukarıdaki "agy engine"
bölümü, öncelik sırası orada net: agy önce, Claude research/judge sonra
(agy başarısız/yetersiz kalırsa). Aşağıdaki 0. adım (health.sh/kota kontrolü)
sadece Claude hesapları için geçerli, agy'de kota-precheck yok.

0. **Sağlık kontrolü:**
   ```bash
   .claude/skills/model-dispatch/scripts/health.sh
   ```
   Birden fazla hesap arasında dağıtacaksan (bkz. "Çoklu hesap dağıtımı")
   HER hesap için ayrı çalıştır (`health.sh akb34`) — bir hesabın kotası
   yüksek diye otomatik ertelemeden önce, aynı işi başka bir hesaba
   yönlendirmenin mümkün olup olmadığına bak.
   JSON çıktısında `quota_status` (`"ok"|"high"|"unknown"`) ve
   `quota_resets_in_minutes` var. Exit 15 ise (`quota_status: "high"` —
   ONAYLANMIŞ ≥%90) — başka bir hesap MÜSAİTSE oraya dispatch et
   (`dispatch.sh ... akb34`); değilse **otomatik ertele:** o dakika değerine ~2dk tampon
   ekleyip `ScheduleWakeup` çağır (`delaySeconds = (quota_resets_in_minutes +
   2) * 60`), kullanıcıya "kota dolu, N dk sonra tekrar deneyeceğim" de, bu
   turu bitir. Uyanınca aynı dispatch'i tekrar dene — `dispatch.sh`'ın
   kendisi de aynı kontrolü yapıp hâlâ yüksekse (nadir ama olabilir) tekrar
   aynı mesajla reddeder, tekrar ertelersin. Exit 1 ise iki farklı sebepten
   olabilir, JSON'a bak: git/worktree/cli/disk sorunu — dispatch etme,
   sorunu çöz/kullanıcıya söyle (bu kota değil, otomatik ertelenmez); YA DA
   `quota_status: "unknown"` (usage.sh arızalı/parse edilemedi) —
   `health.sh` bu durumda artık exit 0 ile fail-open dönüyor (bkz. exit-code
   tablosu, H6 notu), yani pratikte bu koldan exit 1 SADECE gerçek
   git/worktree/cli/disk arızasında gelir; quota_resets_in_minutes `null`
   olduğu için bu koşulda ScheduleWakeup matematiğini KURMA, "kota
   kontrol edilemedi" de ve tekrar dene/kullanıcıya sor.
1. **Task ID'yi belirle.** Ticket'lı işse ticket ID'si (`KYC-121`), değilse
   `new-id.sh`.
2. **Prompt dosyasını yaz — `# GOAL:` ZORUNLU, `# FILES:` opsiyonel:**
   ```
   # GOAL: FE-125 Adım 4 — bekleyen-inceleme tablosunu dashboard'a ekle
   # FILES: services/gateway/src/routes/tenantSelf.js,portals/ops-dashboard/src/pages/portal/DashboardPage.js
   Görev talimatının gerisi burada...
   ```
   `# GOAL:` yoksa `dispatch.sh` başlamadan reddeder (exit 1) — headless ajan
   geri soru soramaz, belirsizliği SEN dispatch'ten önce çöz. `# FILES:` varsa
   çakışma otomatik engellenir.
3. **Dispatch et:**
   ```bash
   .claude/skills/model-dispatch/scripts/dispatch.sh design fe125-adim4 .agent-logs/prompts/fe125-adim4.txt
   ```
   Hemen döner, arka planda çalışır. Birden fazla görevi paralel dispatch
   edebilirsin (farklı `task-id` ile) — `# FILES:` başlığı varsa çakışma
   otomatik engellenir, yoksa dosya seçimini sen elle kontrol et (gorev-loop'un
   "aynı dosyaya iki fixer yazamaz" kuralı burada da geçerli).

   **`dispatch.sh` bitince SANA otomatik haber gelmez** — arka planda kendi
   içinde `&` ile çalışıp anında dönüyor, Bash tool çağrısı o an zaten
   tamamlanmış oluyor, harness'in izleyeceği hiçbir şey kalmıyor. Gerçek bir
   "bitince bildirim" istiyorsan dispatch'ten hemen sonra `wait.sh`'ı Bash
   tool'una `run_in_background: true` ile ver:
   ```bash
   .claude/skills/model-dispatch/scripts/wait.sh fe-171 kyc-179 fe-158 kyc-181 kyc-182
   ```
   (bu çağrıyı arka planda çalıştır — `run_in_background: true`). `wait.sh`
   verilen task'ların HEPSİ bitene kadar `status.sh`'ı polling ile bekletir,
   kendisi bittiğinde harness seni gerçekten bilgilendirir. Sadece
   `status.sh`/`list.sh` tek başına çağırmak "haber bekliyorum" demek DEĞİL —
   o an sonucu okur, gelecekte bitince seni uyarmaz.
3. **Ne dispatch edildiğini unutma:**
   ```bash
   .claude/skills/model-dispatch/scripts/list.sh
   ```
   Her yeni turda (özellikle uzun bir aradan sonra) önce bunu çalıştır — bir
   batch'in "hiç başlamadığı" bu oturumda bir kez fark edilmeden kaldı, bunu
   önlemek için.
4. **Durumu kontrol et:**
   ```bash
   .claude/skills/model-dispatch/scripts/status.sh fe125-adim4
   ```
5. **Bitince raporu + maliyeti oku:**
   ```bash
   .claude/skills/model-dispatch/scripts/collect.sh fe125-adim4
   ```
   `collect.sh` maliyeti (`total_cost_usd`) HER ZAMAN buradan oku (bridge'de yok).
   Rapor metni için writer roller artık `submit_result` MCP tool'una da yapılandırılmış
   veri bırakıyor (bkz. "agent-bridge" bölümü) — `get_result(task_id)` tool'unu ASIL
   kaynak olarak tercih et (yapılandırılmış: status/summary/changed_files/risk/verified),
   `collect.sh`'ın serbest-metin son mesajını sadece bridge boşsa (eski task, Stop hook
   olmadan dispatch edilmiş) fallback olarak kullan.
6. **Diff'i incele — MUTLAKA apply'dan önce:**
   ```bash
   .claude/skills/model-dispatch/scripts/diff.sh fe125-adim4
   ```
   Worktree staleness kontrolü de burada yap (bkz. gorev-loop skill'indeki
   aynı uyarı — worktree HEAD'den dallandığı için genelde taze olmalı, ama
   yine de diff'i gözle doğrula).
7. **Ana checkout'a uygula** (stage/commit YAPMAZ), **exit code'u kontrol et**:
   ```bash
   .claude/skills/model-dispatch/scripts/apply.sh fe125-adim4
   ```
   `git apply` tüm patch'i atomik uygular — birden fazla dosya varsa ve
   BİRİ bile çakışırsa (ör. o dosya main checkout'ta bu worktree'den
   ayrıldıktan sonra elle/başka bir task tarafından değiştirilmiş), HİÇBİR
   dosya yazılmaz, script exit 16 ile döner. Exit code'u görmeden "Applied..."
   metnine güvenme — özellikle aynı dosyaya (ör. bir GOREV_*.md) birden fazla
   task veya elle bir düzenleme dokunmuşsa. Başarısız olursa `git status`/
   içerik grep'iyle çapraz doğrula, gerekirse `diff.sh` çıktısından ilgili
   dosyaları elle (Edit/Write ile) main checkout'a taşı.
8. **Sağlamlaştırılmış doğrulama** — apply'dan sonra (ya da elle bir değişiklik
   yaptıktan sonra da) her zaman:
   ```bash
   .claude/skills/model-dispatch/scripts/verify.sh
   ```
   Sadece o task'ın dosyalarını değil, working tree'de commit'lenmemiş HER
   ŞEYİ tarar — apply.sh'ı unutup elle da bir şey değiştirmiş olabilirsin,
   verify.sh ikisini de yakalar.
9. Normal gorev-loop akışına devam et: `gorev_status.py check-sync <ID>`,
   sonra kullanıcıya sor, onay alınca SEN commit at (dispatch edilen ajan
   değil).
10. **Commit atıldıktan hemen sonra temizliği KENDİN teklif et — atlanan bir
    adım olarak kalmasın.** Commit'i yaptığın anda worktree'ler/branch'ler
    artık gereksiz (dosyalar zaten ana checkout'a `apply.sh` ile kopyalandı,
    commit'lendi) — bunu unutup bir sonraki `list.sh`'a kadar ortalıkta
    bırakma. Tek task için `cleanup.sh <task-id>`, birden fazla task aynı
    turda commit'lendiyse `cleanup-all.sh` (DESTRUCTIVE, ikisi de kullanıcı
    onayı ister):
    ```bash
    # önizleme (--yes olmadan hiçbir şey silmez, sadece listeler):
    .claude/skills/model-dispatch/scripts/cleanup-all.sh --applied
    # kullanıcı onaylayınca:
    .claude/skills/model-dispatch/scripts/cleanup-all.sh --applied --yes
    ```
    `--applied`, worktree'sinde commit'lenmemiş/artık diff kalmamış (yani
    `apply.sh` her şeyi çıkarmış) TÜM task'ları hedefler — "N task'ı bu turda
    commit'ledim, hepsini süpür" senaryosu için. Belirli task-id'leri de
    elle verebilirsin: `cleanup-all.sh fe-158 fe-171 kyc-179 --yes`.

## Kota/kalan-kullanım kontrolü

`/usage` slash komutu sadece interaktif terminalde çalışır, `claude -p`
(headless) modda çalışmıyor. Ama `usage.sh` bunun eşdeğerini script'ten
sağlıyor — `<config-dir>/.credentials.json`'daki OAuth token'ı okuyup
Anthropic'in (belgelenmemiş, önceden haber vermeden değişebilir)
`api.anthropic.com/api/oauth/usage` endpoint'ini sorguluyor:
```bash
.claude/skills/model-dispatch/scripts/usage.sh          # ambient hesap
.claude/skills/model-dispatch/scripts/usage.sh akb34     # belirli bir hesap (bkz. "Çoklu hesap dağıtımı")
```
5 saatlik (session) ve 7 günlük (weekly) kullanım yüzdesini + sıfırlanma
zamanını döndürür. **Her batch dispatch etmeden ÖNCE, dispatch edeceğin
hesap için bunu çalıştır** — kullanım yüksekse (ör. session %90+): önce
BAŞKA bir hesapta headroom var mı bak (`usage.sh <diğer-hesap>`), varsa işi
oraya yönlendir; yoksa sıfırlanma yakınsa (`ScheduleWakeup` ile) o zamana
ertele. Endpoint hata dönerse (kırılmış olabilir) kota hakkında TAHMİN
YÜRÜTME, sadece "kontrol edemedim" de.

`collect.sh` çıktısındaki `total_cost_usd` ayrıca bu OTURUMDA dispatch
edilen işlerin toplam harcamasını izlemek için kullanılabilir (kalan kota
değil, sadece harcama göstergesi — `usage.sh` asıl kota kaynağı).

### Kota tükenince dispatch edilen ajan ne olur (2026-07-17 araştırıldı)

İki ayrı an var, ikisi de farklı davranıyor:

1. **Dispatch ANINDA** (`dispatch.sh` kendi ön-kontrolü) — session %90+ ise
   exit 15 ile REDDEDER, hiç başlatmaz. Bu zaten vardı, sağlam.
2. **RUN SIRASINDA** (task 25dk çalışırken kota biterse) — `claude -p`'de
   kota tükenmesi için OTOMATİK DÜŞÜŞ/fallback YOK. `--fallback-model` flag'i
   var ama o sadece model overload/unavailable durumunu kapsıyor, kullanım
   limiti aşımını değil (CLI help'te doğrulandı). Kota bitince CLI hata
   basıp non-zero exit code ile çıkıyor — sessiz bir model downgrade YOK,
   iş yarım kalıyor.

   Önceden bu durum `status.sh`'ta sıradan "failed" (exit 1) olarak
   görünüyordu — kota mı gerçek bug mı ayırt edilemiyordu, `.err` dosyasını
   elle okumak gerekiyordu. Artık `status.sh` ve `collect.sh`, `.err`
   içinde bilinen kota/rate-limit imzasını (`usage limit`,
   `rate_limit_error`, `exceeded your ... usage/quota`, `429`) arıyor —
   bulursa `status.sh` **exit 17** ("quota_exhausted") döner, `collect.sh`
   PARTIAL raporun üstüne uyarı ekler. **exit 17 gördüğünde**: bunu bug
   olarak loglama/fixer'a verme.

**Sıfırlanınca nasıl devam eder — `resume.sh` (2026-07-17: gerçek session
resume'a geçirildi):**
```bash
.claude/skills/model-dispatch/scripts/resume.sh kyc-190
```
İlk tasarımda (yanlıştı, kullanıcı fark etti) her dispatch `claude -p`'yi
taze bir oturumla başlatıyordu — worktree'deki dosyalar kalıcıydı ama
modelin önceki turlardaki akıl yürütmesi/konuşma geçmişi YOKTU, sadece
dosyaların o anki haline bakıp tahmin ediyordu. Artık gerçek konuşma
devamlılığı var:

- `dispatch.sh` her ilk dispatch'te bir `session_id` (UUID) üretip
  `claude -p ... --session-id <uuid>` ile geçiyor ve `$TASK.meta`'ya
  kaydediyor (`claude -p`, `--no-session-persistence` verilmediği sürece
  oturumu session-id'ye göre diskte tutuyor).
- `resume.sh` bu `session_id`'yi okuyup `DISPATCH_RESUME=1` +
  `DISPATCH_SESSION_ID=<uuid>` ile `dispatch.sh`'ı tekrar çağırıyor;
  `dispatch.sh` bu durumda `--session-id` yerine `--resume <uuid>`
  kullanıyor — GERÇEK önceki konuşma devam ediyor, prompt olarak sadece
  kısa bir "kesintiye uğradın, kaldığın yerden devam et" hatırlatması
  gönderiliyor (orijinal görev metnini ikinci kez "yeni istek" gibi
  göndermek konuşmayı devam ettiren bir modele tuhaf gelirdi).
- `$TASK.meta`'da `session_id` yoksa (bu özellikten önce dispatch edilmiş
  eski bir task) `resume.sh` bunu tespit edip GERİYE DÜŞER: aynı
  worktree/prompt'la ama taze bir konuşmayla devam eder, açıkça uyarır.

Worktree zaten diskte durduğu için (`dispatch.sh` "reusing" der) kesintiye
kadarki dosya değişiklikleri de ayrıca korunuyor — hem dosya durumu hem
konuşma hafızası birlikte taşınıyor.

Akış: kota-red görürsen (`ScheduleWakeup` ile sıfırlanma+2dk'ya ertele) →
uyanınca `resume.sh <task-id>` çağır (eski `.json`/`.err`/`.exitcode`/`.pid`
otomatik `*.prev-<timestamp>` olarak arşivlenir, `status.sh`/`collect.sh`
YENİ çalıştırmayı okur) → dispatch sonrası yine `wait.sh` ile bekle (yukarı
bkz.) → normal `status.sh`/`collect.sh`/`diff.sh` akışına devam et.
`resume.sh` sadece exit 17 (kota) veya 14 (timeout) durumundaki task'ları
kabul eder — hâlâ çalışan ya da temiz bitmiş bir task'ı resume etmeye
çalışırsan exit 18 ile reddeder. `resume.sh` kendi içinde `dispatch.sh`'ı
çağırdığı için o da yeniden kota ön-kontrolü yapar — hâlâ yüksekse (nadir
ama olası) yine exit 15 ile reddeder, tekrar ertelersin.

## Context-window doluluk farkındalığı — `context-usage.sh`

`usage.sh`'ın çözdüğü "kalan hesap kotası" sorunundan AYRI bir sorun: bu ana
oturumun (benim, orkestratörün) kendi context penceresinin ne kadar dolu
olduğunu bilmiyordum — sadece sistem otomatik sıkıştırma yapınca fark
ediyordum. Artık kontrol edilebiliyor:
```bash
.claude/skills/model-dispatch/scripts/context-usage.sh <kendi-session-id>
```
`~/.claude/projects/*/<session-id>.jsonl` transkriptindeki en son
`message.usage` alanından (`input_tokens + cache_creation_input_tokens +
cache_read_input_tokens`) toplam context kullanımını hesaplar, 1M token'a
(bu hesapta gözlemlenen Sonnet context limiti — farklıysa 2. argümanla
override et) oranlar.

**Kendi session ID'in nereden bilinir:** Konuşma boyunca tool-result/hook
payload'larında (`.claude/projects/<proje>/<session-id>.jsonl` yolu, ya da
`sessionId` alanı) zaten görünüyor — bunu ayrıca sorgulamana gerek yok,
context'te zaten var, doğrudan kullan. Otomatik "en son değişen dosya"
tahmini KULLANILMIYOR çünkü aynı projede birden fazla Claude Code oturumu
paralel açık olabiliyor (`claude agents --json` bunu doğruladı) — yanlış
oturumun kullanımını raporlama riski var, bu yüzden session ID'yi bilerek
elle veriyorsun.

**Ne zaman çalıştır:** Uzun bir batch dispatch etmeden önce, ya da genel
olarak oturum uzadıkça periyodik olarak (ör. her ~10-15 turda bir) —
%70+ görürsen kullanıcıya haber ver, önemli state'i notlara/memory'ye
checkpoint'le, gerekirse `/compact` öner.

## Ne zaman kullanılır

- Kullanıcı "3 modele dağıtalım" dediğinde, artık manuel prompt-ver/kopyala-al
  yerine bu akışı kullan (kullanıcı açıkça farklı bir şey istemedikçe).
- Dosya çakışması olmayan, birbirinden bağımsız 2-3 batch varsa paralel
  dispatch et — aynı gorev-loop'un "dosya-çakışması kuralı" burada da geçerli,
  aynı dosyaya dokunacak iki görevi asla ayrı task-slug'a dispatch etme.

## Ne zaman kullanılmaz

- Kullanıcıyla birlikte canlı tartışılan/karar verilen bir konu (brainstorm,
  mimari tercih) — bunlar ana oturumda kalır, dispatch edilmez.
- Commit/push/deploy gerektiren adımlar — bunlar her zaman ana oturumda,
  kullanıcı onayıyla.
