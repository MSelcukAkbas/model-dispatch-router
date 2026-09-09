#!/usr/bin/env node
// agent-bridge — stdio MCP server, orkestrator <-> dispatch edilen alt model
// arasında soru-cevap + yapılandırılmış sonuç kanalı.
//
// İki bağlam:
//   1) Dispatch-scope: dispatch.sh her writer role için --mcp-config ile
//      bunu yükler, DISPATCH_TASK_ID env'i set eder — alt model task_id
//      parametresi vermeden ask_orchestrator/submit_result kullanabilir.
//   2) Proje-scope (.mcp.json, repo kökü) — orkestratörün kendi oturumu,
//      DISPATCH_TASK_ID YOK, list_pending_questions/answer_question/
//      get_result task_id parametresiyle çağrılır.
//
// Depo: .agent-logs/<task>.bridge.json (bu script'in kendi konumuna göre
// hesaplanan repo kökünden — env/cwd'ye bağımlı değil, hem worktree'den hem
// ana checkout'tan aynı dosyaya yazar).
//
// Kilitleme: eşzamanlı okuma-değiştirme-yazma için basit exclusive-create
// lockfile + retry/backoff + stale-lock kurtarma (çökme senaryosu).

'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const knowledgeStore = require('./knowledge-store');
const ollamaEmbed = require('./ollama-embed');

const REPO_ROOT = process.env.DISPATCH_REPO_ROOT
  ? path.resolve(process.env.DISPATCH_REPO_ROOT)
  : process.cwd();
const LOG_DIR = path.join(REPO_ROOT, '.agent-logs');
fs.mkdirSync(LOG_DIR, { recursive: true });

const ASK_POLL_MS = 2000;
const ASK_DEFAULT_TIMEOUT_S = 180;
const ASK_MAX_TIMEOUT_S = 600;
const LOCK_STALE_MS = 15000;
const LOCK_RETRY_MS = 50;
const LOCK_MAX_WAIT_MS = 10000;

function bridgePath(taskId) {
  if (!taskId || typeof taskId !== 'string' || !/^[A-Za-z0-9._-]+$/.test(taskId)) {
    throw new Error(`invalid task_id: ${JSON.stringify(taskId)}`);
  }
  return path.join(LOG_DIR, `${taskId}.bridge.json`);
}

function emptyState(taskId) {
  return { task_id: taskId, questions: [], result: null };
}

// --- Lock: exclusive-create lockfile next to the target, stale-lock aware ---
function acquireLock(filePath) {
  const lockPath = filePath + '.lock';
  const start = Date.now();
  for (;;) {
    try {
      const fd = fs.openSync(lockPath, 'wx');
      fs.writeSync(fd, String(process.pid));
      fs.closeSync(fd);
      return lockPath;
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
      try {
        const age = Date.now() - fs.statSync(lockPath).mtimeMs;
        if (age > LOCK_STALE_MS) {
          fs.unlinkSync(lockPath); // önceki sahip muhtemelen çökmüş, kilidi kır
          continue;
        }
      } catch { /* lock bu sırada kalktıysa görmezden gel, tekrar dene */ }
      if (Date.now() - start > LOCK_MAX_WAIT_MS) {
        throw new Error(`lock timeout on ${path.basename(filePath)} — another process held it >${LOCK_MAX_WAIT_MS}ms`);
      }
      sleepSync(LOCK_RETRY_MS);
    }
  }
}
function releaseLock(lockPath) {
  try { fs.unlinkSync(lockPath); } catch { /* zaten kalkmışsa sorun değil */ }
}

function readState(taskId) {
  const p = bridgePath(taskId);
  if (!fs.existsSync(p)) return emptyState(taskId);
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return emptyState(taskId); // bozuk/yarım yazılmış dosya — sıfırdan başla
  }
}
function writeState(taskId, state) {
  const p = bridgePath(taskId);
  fs.writeFileSync(p, JSON.stringify(state, null, 2));
}
function withLock(taskId, mutator) {
  const p = bridgePath(taskId);
  const lock = acquireLock(p);
  try {
    const state = readState(taskId);
    const result = mutator(state);
    writeState(taskId, state);
    return result;
  } finally {
    releaseLock(lock);
  }
}

function listBridgeFiles() {
  if (!fs.existsSync(LOG_DIR)) return [];
  return fs.readdirSync(LOG_DIR)
    .filter((f) => f.endsWith('.bridge.json'))
    .map((f) => f.slice(0, -'.bridge.json'.length));
}

// Gerçek bloklu senkron bekleme — busy-spin CPU yakmaz. Node ana thread'de
// Atomics.wait desteklenir (worker gerekmez), tool call handler'ları senkron
// olduğu için (JSON-RPC cevabı tek satır, awaitli hale getirmek stdio
// framing'i karmaşıklaştırırdı) bu en temiz seçenek.
const SLEEP_BUF = new Int32Array(new SharedArrayBuffer(4));
function sleepSync(ms) {
  Atomics.wait(SLEEP_BUF, 0, 0, ms);
}

// --- Tool implementations ---

function toolAskOrchestrator(args) {
  const taskId = args.task_id || process.env.DISPATCH_TASK_ID;
  if (!taskId) throw new Error('task_id verilmedi ve DISPATCH_TASK_ID env yok — hangi task için soruluyor belirsiz.');
  const question = String(args.question || '').trim();
  if (!question) throw new Error('question boş olamaz.');
  let timeoutS = Number(args.timeout_seconds ?? ASK_DEFAULT_TIMEOUT_S);
  if (!Number.isFinite(timeoutS) || timeoutS <= 0) timeoutS = ASK_DEFAULT_TIMEOUT_S;
  timeoutS = Math.min(timeoutS, ASK_MAX_TIMEOUT_S);

  const qid = crypto.randomUUID();
  withLock(taskId, (state) => {
    state.questions.push({
      id: qid,
      question,
      asked_at: new Date().toISOString(),
      status: 'pending',
      answer: null,
      answered_at: null,
    });
  });

  const deadline = Date.now() + timeoutS * 1000;
  while (Date.now() < deadline) {
    const state = readState(taskId);
    const q = state.questions.find((x) => x.id === qid);
    if (q && q.status === 'answered') {
      return `Orkestratör cevapladı: ${q.answer}`;
    }
    sleepSync(ASK_POLL_MS);
  }

  withLock(taskId, (state) => {
    const q = state.questions.find((x) => x.id === qid);
    if (q && q.status === 'pending') q.status = 'timed_out';
  });
  return `NO_ANSWER_YET — orkestratör ${timeoutS}s içinde cevap vermedi. Kendi en iyi kararını ver, varsayımını final raporunda (submit_result) açıkça belirt.`;
}

// findings[] her bir kaydı knowledge DB'ye yazar (2026-08-23 karar — ayrı bir
// knowledge_write çağrısı gerekmez, zaten Stop-hook'la zorunlu olan
// submit_result içinde gelir). Tek bir hatalı finding tüm submit_result'ı
// düşürmesin diye her biri bağımsız try/catch'te — biri şema hatası verirse
// diğerleri ve asıl status/summary kaydı yine de işlenir, hata skipped[]'e
// düşer.
async function writeFindings(findings, taskId, sourceRole) {
  if (!Array.isArray(findings) || findings.length === 0) return { written: 0, skipped: [] };
  const cwd = process.cwd(); // dispatch.sh'ın `cd "$RUN_DIR"`'ından miras
  const skipped = [];
  let written = 0;
  for (const f of findings) {
    try {
      const claimText = `${f.topic || ''} ${f.claim || ''}`.trim();
      const embedding = await ollamaEmbed.embed(claimText); // fail-soft: null olabilir
      knowledgeStore.insertKnowledge({
        topic: f.topic,
        category: f.category,
        claim: f.claim,
        evidence: f.evidence,
        scope: f.scope || 'task',
        source_task: taskId,
        source_role: sourceRole,
        embedding,
      }, cwd);
      written++;
    } catch (e) {
      skipped.push({ topic: f && f.topic, error: e.message });
    }
  }
  return { written, skipped };
}

async function toolSubmitResult(args) {
  const taskId = args.task_id || process.env.DISPATCH_TASK_ID;
  if (!taskId) throw new Error('task_id verilmedi ve DISPATCH_TASK_ID env yok.');
  const status = String(args.status || '').trim();
  if (!status) throw new Error('status zorunlu (ör. DONE, PARTIAL, BLOCKED).');
  const summary = String(args.summary || '').trim();
  if (!summary) throw new Error('summary zorunlu.');

  const sourceRole = process.env.DISPATCH_ROLE || null;
  const { written, skipped } = await writeFindings(args.findings, taskId, sourceRole);

  const record = {
    status,
    summary,
    changed_files: args.changed_files ?? null,
    risk: args.risk ?? null,
    verified: args.verified ?? null,
    findings_written: written,
    findings_skipped: skipped,
    submitted_at: new Date().toISOString(),
  };
  withLock(taskId, (state) => { state.result = record; });
  let msg = `submit_result kaydedildi (task=${taskId}, status=${status}, findings_written=${written}).`;
  if (skipped.length > 0) msg += ` UYARI: ${skipped.length} finding şema hatasıyla atlandı: ${JSON.stringify(skipped)}`;
  return msg;
}

function toolListPendingQuestions(args) {
  const taskId = args.task_id;
  const out = [];
  const taskIds = taskId ? [taskId] : listBridgeFiles();
  for (const tid of taskIds) {
    const state = readState(tid);
    for (const q of state.questions) {
      if (q.status === 'pending') {
        out.push({ task_id: tid, question_id: q.id, question: q.question, asked_at: q.asked_at });
      }
    }
  }
  return JSON.stringify(out, null, 2);
}

function toolAnswerQuestion(args) {
  const taskId = String(args.task_id || '').trim();
  if (!taskId) throw new Error('task_id zorunlu.');
  const answer = String(args.answer || '').trim();
  if (!answer) throw new Error('answer boş olamaz.');
  const questionId = args.question_id ? String(args.question_id) : null;

  const outcome = withLock(taskId, (state) => {
    let q;
    if (questionId) {
      q = state.questions.find((x) => x.id === questionId);
      if (!q) throw new Error(`question_id '${questionId}' bulunamadı (task=${taskId}).`);
      if (q.status !== 'pending') return { alreadyResolved: true, status: q.status };
    } else {
      const pending = state.questions.filter((x) => x.status === 'pending');
      if (pending.length === 0) throw new Error(`task '${taskId}' için bekleyen soru yok.`);
      q = pending[pending.length - 1]; // en güncel bekleyen
    }
    q.answer = answer;
    q.status = 'answered';
    q.answered_at = new Date().toISOString();
    return { questionId: q.id };
  });

  if (outcome.alreadyResolved) {
    return `uyarı: soru zaten '${outcome.status}' durumundaydı, cevap yine de kaydedilmedi çünkü artık bekleyen değil.`;
  }
  return `cevap kaydedildi (task=${taskId}, question_id=${outcome.questionId}). Alt model bir sonraki poll turunda görecek (en fazla ${ASK_POLL_MS}ms gecikmeyle).`;
}

function toolGetResult(args) {
  const taskId = String(args.task_id || '').trim();
  if (!taskId) throw new Error('task_id zorunlu.');
  const state = readState(taskId);
  if (!state.result) {
    const pendingCount = state.questions.filter((q) => q.status === 'pending').length;
    return JSON.stringify({ submitted: false, pending_questions: pendingCount }, null, 2);
  }
  return JSON.stringify({ submitted: true, ...state.result }, null, 2);
}

// knowledge_write — submit_result.findings[] dışında, orkestratörün ya da bir
// ajanın turu bitirmeden ARA bir bulguyu kalıcı hale getirmesi gerektiğinde
// (nadir — asıl yol submit_result). Aynı sunucu-taraflı dirty/commit_sha
// hesaplamasını paylaşır.
async function toolKnowledgeWrite(args) {
  const taskId = args.task_id || process.env.DISPATCH_TASK_ID || null;
  const sourceRole = args.source_role || process.env.DISPATCH_ROLE || null;
  const cwd = process.cwd();
  const claimText = `${args.topic || ''} ${args.claim || ''}`.trim();
  const embedding = await ollamaEmbed.embed(claimText);
  const result = knowledgeStore.insertKnowledge({
    topic: args.topic,
    category: args.category,
    claim: args.claim,
    evidence: args.evidence,
    scope: args.scope || 'task',
    source_task: taskId,
    source_role: sourceRole,
    embedding,
  }, cwd);
  return `knowledge kaydedildi (id=${result.id}, topic=${result.topic}, commit_sha=${result.commit_sha || 'yok'}, embedding=${embedding ? 'var' : 'YOK (Ollama erişilemedi — BM25-only)'}).`;
}

// knowledge_search — hibrit BM25+cosine arama. Sorgu embedding'i best-effort
// (Ollama kapalıysa null, arama sadece BM25 ile devam eder — asla boş dönmez
// diye değil, asla ÇÖKMEZ diye).
async function toolKnowledgeSearch(args) {
  const cwd = process.cwd();
  const queryEmbedding = args.query ? await ollamaEmbed.embed(String(args.query)) : null;
  const results = knowledgeStore.searchKnowledge({
    query: args.query,
    topic: args.topic,
    category: args.category,
    status: args.status,
    limit: args.limit,
    queryEmbedding,
  }, cwd);
  return JSON.stringify({ count: results.length, results }, null, 2);
}

// --- MCP tool schema ---
const TOOLS = [
  {
    name: 'ask_orchestrator',
    description: 'Dispatch edilmiş alt model olarak, seni çağıran orkestratör (başka bir Claude oturumu, insan DEĞİL) modele bloke-edici bir soru sor. Cevap gelene ya da timeout_seconds dolana kadar bekler. Sadece gerçekten belirsiz/riskli bir karar noktasında kullan — tahmin edebileceğin şeyi sorma.',
    inputSchema: {
      type: 'object',
      properties: {
        question: { type: 'string', description: 'Tek, net soru.' },
        timeout_seconds: { type: 'number', description: `Maksimum bekleme (varsayılan ${ASK_DEFAULT_TIMEOUT_S}, tavan ${ASK_MAX_TIMEOUT_S}).` },
        task_id: { type: 'string', description: 'Genelde gerekmez — DISPATCH_TASK_ID env otomatik kullanılır.' },
      },
      required: ['question'],
    },
  },
  {
    name: 'submit_result',
    description: 'Görevin BİTİŞİNDE zorunlu final rapor — serbest metin yerine yapılandırılmış. Turu bitirmeden önce mutlaka çağır. findings[]: görev sırasında öğrenilen, gelecekte başka bir ajana yarayabilecek her şeyi buraya yaz — hem istenen görevin sonucunu (scope=task) hem görev dışı ama önemli tesadüfi keşifleri (scope=incidental). Yeni/kalıcı bir bilgi yoksa findings boş bırakılabilir — bu geçerli ve beklenen bir cevaptır, doldurmak için uydurma. Bir incidental finding gördüğünde onu DERINLEMESINE ARAŞTIRMA — sadece gözlemi ve kanıtı kaydet, asıl görevine dön.',
    inputSchema: {
      type: 'object',
      properties: {
        status: { type: 'string', description: 'DONE | PARTIAL | BLOCKED gibi.' },
        summary: { type: 'string', description: 'Ne yapıldığının kısa özeti.' },
        changed_files: { type: 'string', description: 'Değiştirilen dosyalar, virgülle ayrık.' },
        risk: { type: 'string', description: 'Bilinen risk/varsayım varsa.' },
        verified: { type: 'string', description: 'Nasıl doğrulandı (test/lint/manuel).' },
        findings: {
          type: 'array',
          description: 'Yeni/kalıcı bilgi yoksa boş dizi bırak — zorunlu değil, doldurmak için uydurma.',
          items: {
            type: 'object',
            properties: {
              topic: { type: 'string', description: 'Örn: "decision-service.auto-threshold" — serbest ama tutarlı tut, yazma anında otomatik normalize edilir.' },
              category: { type: 'string', description: `Şunlardan biri: ${knowledgeStore.CATEGORIES.join('|')}` },
              claim: { type: 'string', description: 'Tek, net iddia — kod gerçeği, spekülasyon değil.' },
              evidence: {
                type: 'array',
                description: 'Kanıt dosya/satırları — dirty (commit\'lenmemiş) olup olmadığı sunucu tarafında otomatik hesaplanır.',
                items: { type: 'object', properties: { file: { type: 'string', description: 'Repo dosyası, ya da (ops rolü için) ilgili komut satırı — repo file yolu değilse dirty/commit_sha hesaplaması atlanır.' }, line: { type: 'number' } } },
              },
              scope: { type: 'string', description: '"task" (istenen görevin sonucu) | "incidental" (görev dışı tesadüfi keşif). Varsayılan: task.' },
            },
            required: ['topic', 'category', 'claim'],
          },
        },
        task_id: { type: 'string', description: 'Genelde gerekmez — DISPATCH_TASK_ID env otomatik kullanılır.' },
      },
      required: ['status', 'summary'],
    },
  },
  {
    name: 'list_pending_questions',
    description: 'Orkestratör tarafı: bekleyen (cevaplanmamış) tüm soruları listeler. task_id verilmezse TÜM task\'lar taranır.',
    inputSchema: {
      type: 'object',
      properties: { task_id: { type: 'string' } },
    },
  },
  {
    name: 'answer_question',
    description: 'Orkestratör tarafı: bir alt modelin sorusunu cevapla. question_id verilmezse o task\'ın en güncel bekleyen sorusu cevaplanır.',
    inputSchema: {
      type: 'object',
      properties: {
        task_id: { type: 'string' },
        question_id: { type: 'string' },
        answer: { type: 'string' },
      },
      required: ['task_id', 'answer'],
    },
  },
  {
    name: 'get_result',
    description: 'Orkestratör tarafı: bir task\'ın submit_result ile bıraktığı yapılandırılmış sonucu id ile sorgula.',
    inputSchema: {
      type: 'object',
      properties: { task_id: { type: 'string' } },
      required: ['task_id'],
    },
  },
  {
    name: 'knowledge_write',
    description: 'Paylaşımlı ajan bilgi deposuna (SQLite, tüm dispatch\'ler arasında ortak) tek bir kayıt yazar. Genelde ayrıca çağırmana gerek YOK — submit_result.findings[] aynı işi turun sonunda otomatik yapar. Bunu sadece turu bitirmeden ÖNCE bir bilgiyi kalıcı hale getirmen gereken nadir bir durumda kullan.',
    inputSchema: {
      type: 'object',
      properties: {
        topic: { type: 'string' },
        category: { type: 'string', description: `Şunlardan biri: ${knowledgeStore.CATEGORIES.join('|')}` },
        claim: { type: 'string' },
        evidence: {
          type: 'array',
          items: { type: 'object', properties: { file: { type: 'string' }, line: { type: 'number' } }, required: ['file'] },
        },
        scope: { type: 'string', description: '"task" | "incidental". Varsayılan: task.' },
      },
      required: ['topic', 'category', 'claim'],
    },
  },
  {
    name: 'knowledge_search',
    description: 'Paylaşımlı ajan bilgi deposunda arama — hibrit BM25 (tam metin) + cosine (anlamsal, embedding varsa) sıralama. İşe başlamadan önce ilgili topic\'i sorgula — daha önce başka bir ajan aynı konuyu araştırmış olabilir, tekrar taramadan önce kontrol et. Sonuçlar evidence\'ın kayıttan beri kaç commit değiştiğini (stale_warning) otomatik işaretler.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Serbest metin arama (opsiyonel — boşsa sadece filtrelerle listeler).' },
        topic: { type: 'string', description: 'Topic prefix filtresi (normalize edilir).' },
        category: { type: 'string', description: `Şunlardan biri: ${knowledgeStore.CATEGORIES.join('|')}` },
        status: { type: 'string', description: `Şunlardan biri: ${knowledgeStore.STATUSES.join('|')}. Boşsa superseded hariç hepsi.` },
        limit: { type: 'number', description: 'Varsayılan 10, tavan 50.' },
      },
    },
  },
];

const HANDLERS = {
  ask_orchestrator: toolAskOrchestrator,
  submit_result: toolSubmitResult,
  list_pending_questions: toolListPendingQuestions,
  answer_question: toolAnswerQuestion,
  get_result: toolGetResult,
  knowledge_write: toolKnowledgeWrite,
  knowledge_search: toolKnowledgeSearch,
};

// --- MCP stdio JSON-RPC loop (newline-delimited JSON, no Content-Length framing) ---
function send(msg) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}
function sendResult(id, result) {
  send({ jsonrpc: '2.0', id, result });
}
function sendError(id, code, message) {
  send({ jsonrpc: '2.0', id, error: { code, message } });
}

let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buf += chunk;
  let idx;
  while ((idx = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, idx).trim();
    buf = buf.slice(idx + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      continue; // parse edilemeyen satır — protokol dışı gürültü, yut
    }
    handleMessage(msg);
  }
});
process.stdin.on('end', () => process.exit(0));

function handleMessage(msg) {
  const { id, method, params } = msg;
  try {
    if (method === 'initialize') {
      sendResult(id, {
        protocolVersion: '2024-11-05',
        capabilities: { tools: {} },
        serverInfo: { name: 'agent-bridge', version: '1.0.0' },
      });
      return;
    }
    if (method === 'notifications/initialized') {
      return; // bildirim, cevap yok
    }
    if (method === 'tools/list') {
      sendResult(id, { tools: TOOLS });
      return;
    }
    if (method === 'tools/call') {
      const name = params && params.name;
      const args = (params && params.arguments) || {};
      const handler = HANDLERS[name];
      if (!handler) {
        sendResult(id, { content: [{ type: 'text', text: `bilinmeyen tool: ${name}` }], isError: true });
        return;
      }
      // Promise.resolve(...).then(handler) hem sync (ask_orchestrator,
      // list_pending_questions, answer_question, get_result — dönüş değeri
      // otomatik resolved promise'e sarılır) hem async (submit_result,
      // knowledge_write/search — Ollama'ya fetch attığı için Promise döner)
      // handler'ları TEK yolda karşılar — cevap ikisinde de burada, tools/call
      // dönünce değil, promise çözülünce gönderilir.
      Promise.resolve()
        .then(() => handler(args))
        .then(
          (text) => sendResult(id, { content: [{ type: 'text', text: String(text) }] }),
          (e) => sendResult(id, { content: [{ type: 'text', text: `hata: ${e.message}` }], isError: true }),
        );
      return;
    }
    if (id !== undefined) {
      sendError(id, -32601, `bilinmeyen method: ${method}`);
    }
  } catch (e) {
    if (id !== undefined) sendError(id, -32603, e.message);
  }
}
