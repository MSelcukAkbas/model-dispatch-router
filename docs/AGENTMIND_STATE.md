# AgentMind — Durum ve Hedef Dokümanı

**Son güncelleme:** 2026-09-03 · **Commit:** `dd3b57b` · **Test:** 114/114 geçiyor
**Kod:** 3.305 satır kaynak + 1.760 satır test, 12 modül, 10 test dosyası

Bu doküman iki şeyi birden yapar: **(A)** bugüne kadar ne yapıldığını, neden
yapıldığını ve gerçek veride ne bulunduğunu eksiksiz kaydeder; **(B)** sistemin
*son hâlinin* ne olması gerektiğini tarif eder — yani bugünkü kod bittiğinde
"işte tam olarak istediğim şey bu" denebilecek durumu. Bir sonraki oturum bu
dosyayı okuyup sıfırdan bağlam kurmadan devam edebilmeli.

---

## İçindekiler

1. [Neden — problem tanımı](#1-neden--problem-tanımı)
2. [Beş bileşenin envanteri ve rolü](#2-beş-bileşenin-envanteri-ve-rolü)
3. [Mimari kararlar ve gerekçeleri](#3-mimari-kararlar-ve-gerekçeleri)
4. [Kurulum — bir sonraki oturumda ilk adım](#4-kurulum--bir-sonraki-oturumda-ilk-adım)
5. [Tam mimari referans — modül modül](#5-tam-mimari-referans--modül-modül)
6. [Veri şeması — tablo tablo](#6-veri-şeması--tablo-tablo)
7. [Katman durumu (L0–L5)](#7-katman-durumu-l0l5)
8. [Gerçek veride bulunanlar](#8-gerçek-veride-bulunanlar)
9. [Bug günlüğü — bulunan ve düzeltilen 9 hata](#9-bug-günlüğü--bulunan-ve-düzeltilen-9-hata)
10. [Komut envanteri — tam referans](#10-komut-envanteri--tam-referans)
11. [Günlük kullanım akışı](#11-günlük-kullanım-akışı)
12. [**Sistemin son hâli — hedef durum**](#12-sistemin-son-hâli--hedef-durum)
13. [Bilinen sınırlamalar — dürüst liste](#13-bilinen-sınırlamalar--dürüst-liste)
14. [Devam planı — öncelik sırasıyla](#14-devam-planı--öncelik-sırasıyla)
15. [Hızlı başlangıç — bir sonraki oturum](#15-hızlı-başlangıç--bir-sonraki-oturum)

---

## 1. Neden — problem tanımı

Kullanıcının elinde beş güçlü ama birbirini tanımayan parça vardı:
`model-dispatch` (orkestrasyon), `agentic-ssh-mcp` (uzak teşhis), `graphify`
(kod grafiği), `agent-bridge`+`knowledge.db` (ajan bilgisi), ve 31 skill'lik
bir kütüphane (`.agent/skills`). İnceleme sonucu ortaya çıkan tez:

> **Hepsi aynı tek problemi çözüyor — orkestratörün context penceresi ve
> kotası, sistemdeki en kıt kaynak.** Her bileşen bunu harcamamanın farklı bir
> stratejisi: `model-dispatch` başkasının kotasını harcıyor (ayrı hesaplar,
> ayrı motorlar), `agentic-ssh-mcp` ham çıktıyı context'e hiç sokmuyor,
> `graphify` dosya okumak yerine graf sorguluyor, `knowledge.db` yeniden
> türetmek yerine hatırlıyor.

Sorun: **yedi ayrı depo, sıfır ortak anahtar.** "Bu dosyaya hangi task
dokundu, hangi bulguyla, doğrulandı mı" sorusu cevaplanamıyordu — cevabın
parçaları `.agent-logs/*.bridge.json`, `knowledge.db`, `.data/ssh_mcp.db`,
`graphify-out/graph.json`, `.remember/*.md` arasında dağınıktı ve aralarında
bağ yoktu.

AgentMind = bu ortak anahtar. Bir "altıncı araç" değil, beş aracı tek yasa
altında birleştiren çekirdek.

**Hedef-durum tanımı (kabul kriterleri, katman modeli, provenance şeması) ayrı
bir Claude artifact'ında yazılmıştı:**
`https://claude.ai/code/artifact/67513fa9-6bea-476f-9e8e-f3ee6dc9b5af`
*(bu link Claude oturumuna özel — yeni oturumda erişilemeyebilir; bu doküman
o artifact'ın içeriğini de kapsayacak şekilde genişletildi, aşağıda §12'de)*

---

## 2. Beş bileşenin envanteri ve rolü

| Bileşen | Konum | Boyut | Rolü |
|---|---|---|---|
| `model-dispatch` | `references/miras.claude/skills/model-dispatch/` | 1.043 satır spec + 2.254 satır script | Üst katman orkestratör. 7 rol (backend/design/sdk/general/ops/research/judge), 2 motor (Claude `dispatch.sh` / agy `dispatch-agy.sh`), 3 hesap (ambient/akb34/deepseek) |
| `agentic-ssh-mcp` | `references/agentic-ssh-mcp/` | 1.287 satır, 4 MCP tool | Ayrık servis. Uzak SSH teşhis + context bütçeli özetleme. AgentMind'ın test yatağı olarak da kullanıldı |
| `graphify` | `references/graphify/` (klon, referans) | 65.540 satır, 85 modül | Dış bağımlılık (`graphifyy==0.9.53`, PyPI'dan pin'li). Kod → knowledge graph, 29 dil, deterministik AST |
| `agent-bridge` + `knowledge.db` | `references/miras.claude/skills/model-dispatch/mcp/` | 518+344 satır JS | Orkestratör↔alt-model kanalı + SQLite tabanlı paylaşımlı bilgi deposu. Provenance lifecycle'ı (`candidate/verified/stale/superseded/promoted`) burada zaten üretimde vardı |
| `.agent/skills` | `references/.agent/skills/` | 31 skill, 5.900+ satır | Jenerik, proje-agnostik skill kütüphanesi. AgentMind'a bağlanmadı, ayrı bir ada olarak kaldı |

**Ek bulgu (bu oturumda ortaya çıktı):** Daha önce aynı problemi çözmeye
çalışan bir girişim vardı — `Desktop/projeler/MCpAndSkill/MultiAgent/
UlakMultiAgent/` (2.125 satır TypeScript, backend/mcp-server/orchestrator/
process-manager/quota/worktree modülleri, 21 Temmuz'dan beri commit'siz,
durmuş). Kullanıcı kararı: **canlandırılmayacak, referans olarak tutulacak.**
Çözdüğü şey (model-to-model iletişim, kalıcı process yönetimi) L3/L5'e ait ve
L0 olmadan anlamsız kalırdı.

---

## 3. Mimari kararlar ve gerekçeleri

| Karar | Gerekçe |
|---|---|
| Çekirdek dili **Python** | graphify Python kütüphanesi — `graph_diff`, `affected`, `_subgraph_to_text` (token bütçesi zaten içinde) doğrudan import edilir. TS olsaydı graphify subprocess+JSON parse'a mahkûm kalırdık, token-bütçe yardımcısını kaybederdik |
| Python **3.12'ye pin** | graphify'ın 29 tree-sitter grameri sistem Python'ı 3.14'te tam desteklenmeyebilirdi (canlı test edildi: 3.12'de hepsi wheel'dan kuruldu, kaynak derleme yok) |
| AgentMind kodu `skills/model-dispatch/mcp/agentmind/` altında | Model-dispatch ana skill; AgentMind onun hafıza ve doğrulama çekirdeği olarak konumlandırıldı |
| `arvis_code`'a **asla yazma** | Kullanıcının ayrı, korumalı bir projesi. **Kritik kısıt** — bir bug bunu bir kez ihlal etti (bkz. §9 madde 5), hemen düzeltildi ve testle kilitlendi |
| graphify **fork edilmedi** | Aktif geliştirilen dış ürün (YC şirketi). Tam sürüm pin (`==0.9.53`, aralık değil), tek `resolver.py`/`context.py` adaptör katmanı. Upstream değişirse tek dosya güncellenir |
| Provenance sözlüğü **uydurulmadı** | `knowledge-store.js`'de zaten üretimde olan `candidate/verified/stale/superseded/promoted` lifecycle'ı olduğu gibi benimsendi. İlk tasarımda önerilen `ASSERTED/VERIFIED` bunun yeniden icadı olurdu |
| Doğrulama **asla delege edilmedi** | Ajanın "testler geçti" demesi hiçbir zaman kanıt sayılmıyor — kapı (`gate.py`) bu makinede, deterministik kontrollerle koşuyor |
| `dispatch.sh`'a **dokunulmadı** | Kullanıcı isteği. Entegrasyon tek yönlü: AgentMind `.agent-logs`'u ve `knowledge.db`'yi okuyor, hiçbir dispatch script'i değiştirilmedi |
| `am route` **"ölçülmüş router" değil** | Veri bunu desteklemiyor (`finished_at` 0/89, hiçbir task'ın başarılı olup olmadığı kaydedilmiyor). Politika + kanıt seviyesi gösteriliyor, "strong/proven" gibi kelimeler kullanılmıyor — testle kilitlendi |

---

## 4. Kurulum — bir sonraki oturumda ilk adım

```powershell
cd C:\Users\akbas\Desktop\agentmind
uv tool install --editable "./skills/model-dispatch/mcp/agentmind[graph]"
```

`--editable` **zorunlu**. `--force` ile ama editable olmadan `uv tool
install`, sürüm numarası değişmediği için cache'teki eski wheel'ı kullanır —
kaynak dosyadaki düzeltme kurulu `am` komutuna hiç yansımaz. Bu oturumda bu
tuzağa iki kez düşüldü (bkz. §9 madde 3).

**Depo zaten kurulu ve dolu**, sıfırdan kurulum GEREKMİYOR:
- `C:\Users\akbas\Desktop\agentmind\.agentmind\am.db` — 89 task, 232+ claim, 276 event
- `~/.agentmind/workspaces` — workspace kayıt defteri, `agentmind` kayıtlı
- `am` PATH'te, herhangi bir dizinden (`arvis_code` içinden dahil) çalışıyor

Doğrulama:
```powershell
uv run pytest -q          # skills/model-dispatch/mcp/agentmind/ içinden, 114 geçmeli
am status                 # herhangi bir yerden
```

---

## 5. Tam mimari referans — modül modül

```
agentmind/                              repo kökü (git reposu, 13 commit)
├── README.md                          kısa proje ve dizin rehberi
├── docs/AGENTMIND_STATE.md            bu dosya
├── .gitignore                          referans klonlar + runtime state hariç
├── skills/model-dispatch/              ana skill + dispatch scriptleri
│   └── mcp/
│       ├── bridge/                     canlı alt-ajan iletişimi
│       └── agentmind/                  Python hafıza/doğrulama çekirdeği
├── docs/research/                      araştırma notları
├── references/                         salt-okunur referans depoları, izlenmiyor
└── .agentmind/, snapshots/             çalışma zamanı verisi, izlenmiyor
```

### `skills/model-dispatch/mcp/agentmind/src/agentmind/` — modül modül (satır sayısı ile)

| Dosya | Satır | Sorumluluk | Anahtar fonksiyon/sınıf |
|---|---:|---|---|
| `store.py` | 671 | Tek SQLite bağlantısı + tüm sorgular | `Database` (bağlantı/şema), `Repository` (sorgular). `agentic-ssh-mcp`'nin `app/db/` ayrımını taklit eder |
| `cli.py` | 1.067 | `am` komutunun tamamı | Typer app, 21 komut, `_open()`/`_target()` ortak yardımcılar |
| `context.py` | 279 | Graf + claim'lerden token-bütçeli prompt üretimi | `build_context()`, `build_file_context()` (taban çizgisi), `_collect_claims()` (STATUS_RANK ile sıralama) |
| `resolver.py` | 234 | claim evidence ↔ graph node JOIN | `resolve_claims()`, `FileIndex` (bisect ile satır→sembol eşleme) |
| `importer.py` | 222 | `.meta` + `knowledge.db` → `am.db` | `import_snapshot()`, `parse_meta()`, `ROLE_MODEL` haritası |
| `gate.py` | 187 | candidate→verified doğrulama kapısı | `evaluate_task()`, `Check`/`GateResult`, `run_command()` |
| `router.py` | 158 | Politika + kanıt seviyesi (routing DEĞİL) | `POLICY` dict, `recommend()`, `confidence()`, `memory_gaps()` |
| `sync.py` | 142 | Canlı repoyu okuyup am.db'yi güncelleme | `sync()`, `_demote_stale_verified()` |
| `snapshot.py` | 109 | Tek yönlü, salt-okunur kopya alma | `take_snapshot()`, `_copy_sqlite_readonly()` (backup API) |
| `workspace.py` | 93 | Depo bulma — yukarı arama + kayıt defteri | `locate_store()`, `_watches()`, `register()` |
| `freshness.py` | 86 | Deterministik git-tabanlı tazelik kontrolü | `is_dirty()`, `commits_since_evidence()` — knowledge-store.js'in JS fonksiyonlarının Python portu |
| `codegraph.py` | 49 | graphify.extract() sarmalayıcısı | `extract_repo()` (her zaman `parallel=False` — Windows'ta pool çöküyor) |
| `__init__.py` | 8 | — | — |

### `skills/model-dispatch/mcp/agentmind/tests/` — 10 dosya, 1.760 satır, 114 test

Her modülün kendi test dosyası var. En kapsamlılar: `test_context.py` (206
satır, budget/ranking/baseline), `test_sync.py` (203 satır, idempotency +
gate-verdict-korunumu), `test_gate.py` (194 satır, pass/fail/promote
senaryoları), `test_router.py` (181 satır, confidence-band + "strong/proven
asla kullanılmaz" testi).

---

## 6. Veri şeması — tablo tablo

`skills/model-dispatch/mcp/agentmind/src/agentmind/schema.sql`, tek SQLite dosyası (`am.db`, WAL modu).

```sql
events        -- L0: append-only olay günlüğü. id, ts, kind, task_id, run_id,
              -- actor, payload_json. Hiçbir satır asla UPDATE/DELETE edilmez.

tasks         -- dispatch.sh'ın .meta dosyalarının normalize edilmiş hâli.
              -- task_id (PK), role, model, engine ('claude'|'agy'), account,
              -- effort, budget_usd, attempt, diffstat, session_id,
              -- no_worktree, config_dir, status, started_at,
              -- started_at_exact (0=mtime'dan tahmin, 1=gerçek), finished_at,
              -- source ('import'|'live')

claims        -- knowledge.db'nin `knowledge` tablosunun aynası + genişletme.
              -- id, topic, category, claim, evidence_json ([{file,line}]),
              -- scope, commit_sha, source_task, source_role,
              -- status ('candidate'|'verified'|'stale'|'superseded'|'promoted'),
              -- verification_count, supporting_tasks_json, superseded_by,
              -- created_at, last_verified_commit, last_verified_at,
              -- origin ('import'|'live'),
              -- source_status  -- kaynağın KENDİ görüşü, bizim status'ümüzden
              --                   AYRI tutulur (bkz. §9 madde 9)

node_refs     -- L1: JOIN tablosu. claim_id, evidence_idx, file, line,
              -- graph_node_id, resolved_at,
              -- dangling (0|1),
              -- reason ('resolved'|'file_missing'|'not_extracted'|'unresolved')
              --   -- file_missing = gerçek kod kayması
              --   -- not_extracted = dosya var ama extractor yok (örn. .yaml)
              --   -- bu ayrım kendi tooling eksiğimizi kullanıcı sorunu gibi
              --      göstermemek için bilinçli olarak yapıldı (bkz §9 madde 8-benzeri)

graph_nodes   -- extract edilmiş kod grafiği, repo-scoped.
              -- (repo, node_id) PK, label, source_file, source_line (int,
              -- graphify'ın "L42" formatından parse edilmiş), node_kind,
              -- file_type, built_at

graph_edges   -- (repo, source, target, relation) UNIQUE.
              -- confidence ('EXTRACTED'|'INFERRED'|'AMBIGUOUS' — graphify'ın
              -- kendi vokabüleri, test_graphify_contract.py ile kilitli)

corpora       -- name (PK) → source_path. "Yol bir kez yazılır" mekanizması —
              -- am setup bir kez source path'i kaydeder, sonraki her komut
              -- --repo/--src olmadan çalışabilir
```

**Kritik tasarım notu:** `claims.status` ve `claims.source_status` bilerek
ayrı. `status` bizim — kapının verdiği karar. `source_status` kaynağın
(knowledge.db) kendi görüşü. Bu ayrım olmadan her `am sync`, her doğrulamayı
sessizce geri alıyordu (§9 madde 9, en ciddi bug'lardan biri).

---

## 7. Katman durumu (L0–L5)

| Katman | Durum | Kanıt |
|---|---|---|
| **L0** — Olay günlüğü + varlık kimlikleri | ✅ tamam | `events` tablosu, 276 kayıt, `am event` fail-open tasarım |
| **L1** — Overlay graph (claim↔kod JOIN) | ✅ tamam | 436/487 ref bağlı (%89-90 aralığında, sync'e göre dalgalanıyor) |
| **L2** — Token-bütçeli context enjeksiyonu | ✅ tamam, **ölçüldü** | Gerçek görevlerde %90-98 token tasarrufu |
| **L3** — Doğrulama kapısı | ✅ tamam | `candidate→verified`, 4 deterministik kontrol, gerçek veride ayrım yaptığı kanıtlı |
| **L4** — Router | ⚠️ bilinçli olarak kısmi | "Ölçülmüş" DEĞİL — politika + kanıt seviyesi. Neden yeterli veri yok, aşağıda açıklanıyor |
| **L5** — TUI | ❌ yapılmadı | Sırada, en ucuz katman (veri zaten toplanıyor) |

---

## 8. Gerçek veride bulunanlar

Tüm bu bulgular `arvis_code` üzerinde **salt-okunur** snapshot/sync ile elde
edildi. Her adımda `git -C arvis_code status --porcelain` ile repo bütünlüğü
doğrulandı.

### Sayılar (güncel — `am status` çıktısı)
- **89-92 dispatch** (sync'e göre değişiyor), **232+ claim**, **276 event**
- **2.285 kod grafiği düğümü, 3.751 kenar**
- **436/487 referans bağlandı (%89-90)**

### Dispatch dağılımı — önceden bilinmeyen bir gerçek
Dispatch'lerin **%73'ü agy'de, %27'si Claude'da** koşmuş. Bu, kullanıcının
"agy'yi öncelikli kullan" politikasının ne kadar agresif uygulandığının ilk
somut ölçümüydü.

### Context enjeksiyonu — tez kanıtlandı
5 gerçek görevde: **567.433 → 20.538 token (%97 az, 27.6x)**.
İlk ölçüm 12.6x çıkmıştı — bu bir kazanç değil, bendeki bir bug'dı: `--budget`
sadece graf gövdesini sınırlıyordu, sonrasına eklenen claim bölümü sınırsızdı.
62 claim'li bir görev "2000 token bütçeli" 13 bin tokenlik prompt üretiyordu.
Düzeltme sonrası claim'ler STATUS_RANK'e göre sıralanıp kendi bütçesinde
kesiliyor.

**İkinci bulgu (daha sonraki oturumda):** `am bench "görev tanımı"` 132.9x
gösterdi — ama bu da sahte çıktı, çünkü sorgu 1.1 MB'lık `GOREV_1_BACKEND.md`
dosyasını yakalamıştı. Oran, o dosyanın boyutunu ölçüyordu, aracı değil.
Düzeltme: `bench` artık "bu sonuçta tek dosya baskın (%X)" uyarısı veriyor.

### Dangling referanslar — ayrıştırılmış kök nedenler
Toplam ~47-51 bağlanamayan referans, ikiye ayrıldı:
- **`file_missing`** (gerçek kod kayması): 7 dosya, ör. `services/kyc-engine/
  shared/verificationDecision/verificationPolicy.js` — **silinmiş ama 4 ayrı
  task hâlâ onun hakkında iddia taşıyor** (DS-R2, EV-R4,
  EVD-REVIEW-1-DATA-LAYER, T-000270)
- **`not_extracted`** (dosya var, extractor yok): 11 dosya, çoğunlukla YAML

### Kapı testi — ayrım yapıyor
- `EV-R3` → **düştü**: kanıt 11-12 commit bayat
- `DS-R2` → **düştü**: `verificationPolicy.js` silinmiş
- `kb-ai-comparison-traffic` → **geçti** → sistemin tarihindeki **ilk
  `verified` iddia**

### 🔴 En önemli bulgu — hafıza deliği
```
am coverage:
  research on agy: 59 runs, 0 claims
  judge on agy:     8 runs, 0 claims
```
**Dispatch'lerin ~%67'si (agy üzerinden koşanlar) hiçbir şeyi hafızaya
yazmıyor.** Kök neden: `submit_result`'ı taşıyan `agent-bridge` MCP sunucusu
yalnızca Claude tarafına bağlı; `dispatch-agy.sh`'ın task-başına MCP config'i
yok — bu, `model-dispatch/SKILL.md`'nin kendisinin belgelediği bir sınırlama
("Per-task `--mcp-config` yok... kalıcı, paylaşımlı `agy mcp add` kaydı").

**Sonuç:** en çok kullanılan, en ucuz motorun (agy) bulduğu her şey
buharlaşıyor. 67 koşu bir şeyler buldu, hiçbiri knowledge store'a ulaşmadı.

Bu tek satır, `am route`'un önerebileceği herhangi bir yönlendirme
tavsiyesinden daha değerli — çünkü **plumbing** sorunu, model kalitesi sorunu
değil.

---

## 9. Bug günlüğü — bulunan ve düzeltilen 9 hata

Hepsi commit'li, hepsi **gerçek veriyle çalıştırılınca** bulundu — kod okuyarak
değil. Bu, gelecekteki geliştirme için tekrarlanması gereken disiplin.

| # | Bug | Bulunuş şekli | Düzeltme | Commit |
|---|---|---|---|---|
| 1 | agy `.meta` farklı format — model'i doğrudan yazıyor, `ROLE_MODEL` türetmesi üstüne yazıyordu | `am tasks` çıktısında agy dispatch'lerinin yanlış model gösterdiği fark edildi | `engine` sütunu eklendi, açık değer her zaman kazanıyor | `419c2da` |
| 2 | agy satırları "ambient Claude" gibi görünüyordu (account alanı yok) | `am stats` sayıları tutarsızdı | İstatistikler `engine`'e göre de gruplanıyor | `419c2da` |
| 3 | `uv tool install --force` eski wheel kullanıyordu | İki tur düzeltme kurulu komuta hiç yansımamıştı | `--editable` kullanılıyor | `db9ccb5` |
| 4 | Yanlış dizinde sessizce boş DB yaratılıyordu | `am status` kökten çalıştırılınca "0 task" gösterdi (veri kaybı gibi göründü) | Yalnızca `init`/`setup` yaratabiliyor | `db9ccb5` |
| 5 | Depo bir üst dizinden bulunamıyordu | Kullanıcı `Desktop`'tan `am status` çalıştırdı, hata aldı | `nearby_stores()` — bir alt dizine bakıp öneri veriyor | `0c6a31e` |
| 6 | rich markup çöküyordu (`[...]` claim metninde) | `am why` çalıştırılınca traceback | `_fmt()` her yerde `rich.markup.escape` kullanıyor | `09507f2` |
| 7 | UnicodeEncodeError (cp1254) | Aynı komut, farklı claim'de `→` karakteri | stdout/stderr `errors="replace"` ile UTF-8'e zorlandı | `09507f2` |
| 8 | `am bench` 132.9x gibi sahte sayı üretti | Kullanıcı gerçek sorguyla test etti, sonuç şüpheli göründü | "Tek dosya baskın" uyarısı + `biggest_file`/`biggest_share` alanları | `8f05211` |
| 9 | **🔴 En ciddi:** `am sync`, izlenen `arvis_code` reposu içinden çalıştırılınca oraya `.agentmind/` yazdı | Kullanıcının kendi terminalinde çalıştırdığı komuttan bulundu, hemen kontrol edildi, dosya silindi, `git status` ile doğrulandı | `_open()`'da explicit `--root` artık "yoksa yarat" anlamına gelmiyor; `workspace.py` kayıt defteri + `_watches()` mekanizması eklendi; `test_a_read_command_never_creates_a_store` testle kilitlendi | `a6811f0` |
| 10 | `am sync`, kapının verdiği `verified` durumunu re-import'ta siliyordu | İkinci kez sync çalıştırılınca `verified` claim tekrar `candidate` oldu, fark edildi | `status`/`verification_count`/`last_verified_*` artık "bizim", import dokunmuyor; `source_status` ayrı sütun | `dae4686` |

**Madde 9, en kritik olanı.** Kullanıcının açık kısıtı ("arvis_code'a
dokunmak yasak") bir bug yüzünden bir kez ihlal edildi. Anında tespit edilip
düzeltildi ve regresyon testiyle kilitlendi, ama bu olayın kaydı burada
kalmalı: **gelecekteki her yeni komut/özellik için, "izlenen repoya yazar mı"
sorusu explicit olarak sorulmalı ve testle kanıtlanmalı.**

---

## 10. Komut envanteri — tam referans

```
KURULUM / BAKIM
  init                    .agentmind/am.db oluştur
  setup <repo>            snapshot+import+graph+resolve tek komutta (İLK KURULUM)
  sync [<repo>]           canlı repoyla güncel kal (GÜNLÜK, argümansız çalışır)
  snapshot <repo>         yalnızca kopya al (salt-okunur)
  import <snapshot>       yalnızca yükle

HAM VERİ GÖRÜNÜMLERİ
  tasks / events / claims / stats
  status                  tek ekranda özet (kabul kriteri K10)
  coverage                kayıt neyi cevaplayabiliyor neyi cevaplayamıyor

GRAF / JOIN
  graph build / graph info
  resolve                 claim↔graf JOIN'i yeniden kur

BİLGİ SORGULARI (dispatch öncesi)
  why <dosya>              bu dosya hakkında ne biliniyor, taze mi
  dangling [--reason]      çürümüş referanslar (file_missing/not_extracted ayrımlı)
  hot                      en çok atıf alan dosyalar

PROMPT ÜRETİMİ (dispatch öncesi)
  context <sorgu>          graf-tabanlı context'i yazdır
  prompt <sorgu> --goal    dispatch.sh-hazır prompt dosyası üret
  bench <sorgu...>         dosya vs graf token karşılaştırması (skew uyarılı)

DOĞRULAMA (task sonrası)
  gate <task> [--promote]  candidate→verified
  gate-targets             doğrulanmayı bekleyen kuyruk
  graph-diff               yapısal değişim ölçümü

YÖNLENDİRME (kısmi — bkz §14)
  route [rol]               politika + kanıt seviyesi
```

**21 komut toplam.** Hepsi `--root` ve `--repo`/`--src`'i opsiyonel alıyor —
bir kez `am setup` çalıştırılınca gerisi hafızadan doluyor (`corpora` tablosu).

---

## 11. Günlük kullanım akışı

```powershell
cd C:\Users\akbas\Desktop\projeler\arvis_code    # izlenen repo içinden

am sync                                          # 1. güncelle
am why services/decision-service/core/reuse.js   # 2. dokunmadan önce öğren
am prompt "reuse eligibility bug" --goal "Fix X" --out gorev.txt   # 3. ucuz prompt
# ... dispatch et ...
am gate KYC-999 --check "npm test" --promote     # 4. doğrula
```

Periyodik: `am status`, `am coverage`, `am gate-targets`, `am dangling
--reason file_missing`.

---

## 12. Sistemin son hâli — hedef durum

Bu bölüm, kod tamamlandığında sistemin nasıl davranması gerektiğini tarif
eder. Önceki artifact'taki (link §1'de) 10 kabul kriteri buraya taşındı ve
bugünkü durumla eşleştirildi.

### 12.1 Değişmez yasa (yeniden ifade)

> Bir işin nereye gideceğini, o işin dolar maliyeti değil; orkestratörün
> context'ini ve kotasını ne kadar yakacağı belirler.

Bu yasa, sistemin verdiği **her** kararın (hangi model, hangi hesap, prompt'a
ne konacak, sonuç nasıl saklanacak) türevi olmalı. Bugün bu yasa L2'de
(context enjeksiyonu) somutlaşmış durumda; L4'te (router) henüz somutlaşmadı
çünkü veri yetersiz.

### 12.2 On kabul kriteri — bugünkü karşılıkları

| # | Kriter | Bugünkü durum |
|---|---|---|
| K01 | Prompt'a dosya değil subgraph gidiyor | ✅ `am prompt --mode graph` |
| K02 | Task bitince bulgular kendiliğinden graph'a yazılıyor | ⚠️ **kısmi** — yalnızca Claude dispatch'leri (agy'nin %67'si hafızaya yazmıyor, bkz §8) |
| K03 | İkinci dokunuş, birincinin bulduğunu sormadan biliyor | ✅ `am why`, ama yalnızca hafızaya giren claim'ler için (K02'ye bağımlı) |
| K04 | Doğrulanmamış iddia karar dayanağı olamıyor | ✅ `am gate`, kapı olmadan `verified` olamaz |
| K05 | Model seçimi ölçülmüş veriye dayanıyor, gerekçeli | ⚠️ **kısmi** — `am route` gerekçe veriyor ama "ölçülmüş" değil, kanıt seviyesi düşük |
| K06 | Kota dolunca iş otomatik kayıyor | ❌ **yapılmadı** — `dispatch.sh`'a dokunulmadı, bu otomasyon L4'ün tam otomatikleşmesini gerektirir |
| K07 | Yeni motor eklemek bir adapter yazmak | ⚠️ **kısmi tasarım var** — `sync.py`/`importer.py` iki motoru (`claude`/`agy`) ayrı ayrı ele alıyor ama resmi bir adapter arayüzü (protokol/ABC) henüz yok |
| K08 | Uzak teşhis + kod bilgisi aynı grafikte | ❌ **yapılmadı** — `agentic-ssh-mcp`'nin `jobs`/`request_log` tabloları `am.db`'ye hiç bağlanmadı |
| K09 | Bir ay önceki karar, gerekçesi ve kanıtıyla tek sorguda geri geliyor | ⚠️ **kısmi** — `am why` + `events` tablosu bunu kısmen sağlıyor, ama `Decision`/`SUPERSEDES` gibi ilişkisel bir kavram henüz modellenmedi |
| K10 | Tek ekranda: koşan, maliyet, kota, doğrulama bekleyenler | ✅ `am status` + `am coverage` + `am gate-targets` (üç komuta bölünmüş ama hepsi var) |

**Özet:** L0-L3 kriterleri (K01, K04, K10) tam karşılanıyor. L2'nin hafıza
tarafı (K02, K03) agy köprüsü eksikliği yüzünden yarım. L4/L5 kriterleri
(K05, K06, K07, K08, K09) henüz erken aşamada veya hiç başlanmadı.

### 12.3 Son hâlde olması gereken ek yetenekler

Bunlar bugün var olmayan ama "elle tutulur ürün"den "tam sistem"e geçiş için
gereken parçalar:

**A. agy → hafıza köprüsü (en yüksek öncelik — kullanıcı onayladı)**
İki olası yaklaşım:
1. `agy mcp add` ile kalıcı (global, task-başına değil) bir bridge kaydı —
   agy'nin her çağrısı otomatik olarak `submit_result`'a erişebilir hale gelir
2. `dispatch-agy.sh`'ın metin çıktısını post-process eden bir adım — agy'nin
   ürettiği raporu parse edip `am event`/claim olarak yazmak

İkisi de `skills/model-dispatch/mcp/agentmind/` içinde kalabilir, `arvis_code`'a dokunmadan (agy'nin
kendi çıktı dosyalarını okuyarak) yapılabilir. Bu köprü kurulmadan K02/K03
tam sağlanamaz ve L4'ün router'ı asla yeterli veriye ulaşamaz — çünkü
dispatch'lerin çoğunluğu (agy) sonuç bırakmıyor.

**B. Resmi execution adapter sözleşmesi (K07)**
Şu an `claude` ve `agy` motorları `importer.py`/`sync.py` içinde ad-hoc
şekilde ayrılıyor (`engine` sütunu ile). Son hâlde bu bir protokol olmalı:

```python
class DispatchAdapter(Protocol):
    def dispatch(self, prompt: str, role: str) -> DispatchHandle: ...
    def collect(self, handle: DispatchHandle) -> DispatchResult: ...
    # DispatchResult: {status, diff, cost, tokens, findings[]}
```

Yeni bir motor (OpenRouter, Qwen — kullanıcının belirttiği gelecek ihtiyaç)
eklemek o zaman bu protokolü implemente etmek olur, `store.py`/`router.py`'a
dokunmadan.

**C. Uzak teşhis ↔ kod grafiği birleşimi (K08)**
`agentic-ssh-mcp`'nin `jobs` ve `request_log` tabloları (host, command,
exit_code, timestamp) `am.db`'ye hiç bağlanmadı. Son hâlde bir `Incident`
düğüm tipi eklenip `Host`'a ve ilgili koddaki sembole bağlanmalı — "bu
incident hangi hosttaki hangi komuttan, hangi koda işaret ediyor" sorgusu tek
traversal'da cevaplanabilmeli.

**D. Karar/ilişki modeli (K09)**
Bugün `claims` tablosu düz bir liste — bir claim'in başka bir claim'i
geçersiz kıldığı (`superseded_by` sütunu var ama hiç kullanılmıyor) ya da bir
kararın hangi bulgulara dayandığı ilişkisel olarak sorgulanamıyor. Son hâlde
`superseded_by` zinciri aktif kullanılmalı ve `am why` bu zinciri gösterebilmeli.

**E. Otomatik kota-kayması (K06)**
`am route`'un ürettiği tavsiye şu an salt-okunur — hiçbir dispatch akışına
otomatik enjekte edilmiyor. Son hâlde ya `dispatch.sh`'a (kullanıcı izin
verirse) ya da yeni bir orkestratör katmanına bu tavsiye canlı olarak
beslenmeli, ve kota olayı `events` tablosuna düşüp bir sonraki dispatch'i
otomatik yönlendirmeli.

**F. TUI (L5)**
Şu an her şey CLI çıktısı. Son hâlde `am.db` üzerine salt-okunur bir görünüm:
canlı run board (task/maliyet/kota/hesap), graf gezgini (graphify'ın
`graph.html`'i zaten hazır, entegre edilmeli), karar günlüğü, kota ısı
haritası. Bu katman veri toplama bittikten sonra en ucuz iş — çünkü `am.db`
zaten her şeyi tutuyor, TUI sadece okuyor.

### 12.4 "Son hâl" tanımının testi

Sistem şu cümleleri hepsi doğru olduğunda hedefine ulaşmış sayılır:

1. Bir task, hangi motorda (Claude veya agy) koşarsa koşsun, ürettiği bulgu
   `am.db`'ye ulaşır — bugün yalnızca Claude tarafı için doğru.
2. Yeni bir motor eklemek, `router.py`/`store.py`'a dokunmadan sadece bir
   adapter sınıfı yazmaktır.
3. `am route`'un verdiği tavsiye en az "weak" güven seviyesinde — yani her
   rol için en az 10 ölçülmüş (başarı/başarısızlık bilinen) dispatch var.
4. Uzak bir SSH teşhisi ile ilgili kod sembolü arasında `am why` benzeri bir
   sorguyla yol bulunabiliyor.
5. Kota dolduğunda insan müdahalesi olmadan bir sonraki dispatch farklı
   hesaba/motora kayıyor ve bu olay `events`'e düşüyor.
6. `am status` tek ekranda hem kod tarafını hem uzak-teşhis tarafını hem de
   router'ın güven seviyesini gösteriyor.

---

## 13. Bilinen sınırlamalar — dürüst liste

- **Otomatik değil.** `am sync`'i elle çalıştırman gerekiyor; iş olurken
  değil, olduktan sonra görüyor. Bu, "izlenen repoya dokunmama" kısıtının
  kaçınılmaz bedeli.
- **`am route` bir router değil**, tavsiye + kanıt seviyesi. Hiçbir task'ın
  başarılı olup olmadığı kaydedilmiyor (`finished_at` 0/89, `diffstat` 0/89).
  "strong"/"proven" gibi kelimeler bilinçli olarak hiç kullanılmıyor (test:
  `test_no_band_is_called_strong_or_proven`).
- **Dispatch kaydının yarısı eksik alan taşıyor** çünkü iki motor farklı
  `.meta` şekli yazıyor: `effort`/`budget_usd`/`attempt`/`session_id` yalnızca
  `dispatch.sh` (Claude) tarafından dolduruluyor, 22/89 satırda var.
- **DeepSeek API anahtarı hâlâ diskte düz metin**
  (`references/miras.claude/skills/model-dispatch/scripts/accounts.sh`,
  `claude-deepseek.bat`, hem `agentmind/` hem `Desktop/` kökünde kopyaları
  var). Repo tarafı `.gitignore` ile korunuyor (`git grep` ile doğrulandı,
  hiçbir izlenen dosyada yok) ama anahtarın kendisi rotate edilmedi — bu
  kullanıcının yapması gereken bir işlem, AgentMind'ın kapsamı dışında.
- **`ops` rolünde SSH komut içeriği filtrelenmiyor** — bu `model-dispatch`'in
  kendi belgelediği bir risk (`--disallowedTools` prefix-match denylist,
  sandbox değil), AgentMind bunu değiştirmedi ve değiştiremez (o katman
  `dispatch.sh`'a ait, dokunulmadı).
- **graphify'ın SQL/YAML gibi bazı dosya tipleri için extractor'ı yok**
  (`not_extracted` referansların çoğunluğu bu yüzden). `[sql]` extra'sı
  eklendi ama YAML/JSON hâlâ desteklenmiyor.

---

## 14. Devam planı — öncelik sırasıyla

### A. agy → hafıza köprüsü *(kullanıcı onayladı, henüz kod yazılmadı)*
En yüksek öncelik — bkz. §12.3.A. Dispatch'lerin %67'sinin hafızaya
yazmamasını çözer, K02/K03'ü tamamlar, L4 router'ının ileride gerçekten
"ölçülmüş" olabilmesinin ön koşuludur.

### B. Resmi adapter protokolü (K07)
agy köprüsü kurulduktan sonra doğal bir sonraki adım — iki motoru
(`claude`/`agy`) ortak bir arayüz altına almak, üçüncü bir motor (OpenRouter
vb.) eklemeyi kolaylaştırır.

### C. L5 — TUI
En ucuz katman, veri zaten toplanıyor. agy köprüsü kurulduktan sonra
anlamlı — aksi halde toplanan verinin üçte biri eksik görünür.

### D. Uzak-teşhis ↔ kod grafiği birleşimi (K08)
`agentic-ssh-mcp` tabloları `am.db`'ye bağlanmadı, kapsam genişletmesi.

### E. `dispatch.sh` entegrasyonu (kullanıcı isterse)
Şu an `am` tamamen ayrı çalışıyor. İstenirse `am event` çağrıları
`dispatch.sh`'ın kendisine eklenebilir — fail-open tasarım bunun için var,
geri dönüşü kolay. **Kullanıcı onayı olmadan yapılmayacak.**

---

## 15. Hızlı başlangıç — bir sonraki oturum

```powershell
cd C:\Users\akbas\Desktop\agentmind\skills\model-dispatch\mcp\agentmind
uv run pytest -q                    # 114 geçmeli (artabilir)
am status                           # anlık durum
am coverage                         # hafıza deliğini gör
```

**Kaldığımız yer:** agy→hafıza köprüsü üzerinde çalışmaya başlamak üzereydik
(§14.A). Kullanıcı onayladı, henüz hiçbir kod yazılmadı. İki yaklaşım
tartışıldı (`agy mcp add` global bridge vs. post-process parse adımı) —
hangisinin seçileceği bir sonraki oturumda netleştirilmeli.

**Referans linkler:**
- İdeal sistem tanımı (artifact): `https://claude.ai/code/artifact/67513fa9-6bea-476f-9e8e-f3ee6dc9b5af`
- `model-dispatch` spec: `references/miras.claude/skills/model-dispatch/SKILL.md`
- graphify mimarisi: `references/graphify/ARCHITECTURE.md`
