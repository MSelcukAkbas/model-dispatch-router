// knowledge-store — SQLite (node:sqlite, deneysel ama Node 24'te FTS5 dahil
// çalıştığı doğrulandı) tabanlı paylaşımlı ajan bilgi deposu.
//
// Depo: .claude/knowledge/knowledge.db (REPO_ROOT-relative, __dirname'den
// hesaplanan — agent-bridge.js'in aynı H1-fix desenini tekrar ediyor: hangi
// repo'da fiziksel olarak durduğuna bağlı, env/cwd'ye değil).
//
// Şema kararları (konuşma geçmişinden):
//   - confidence float YOK — status lifecycle (candidate/verified/stale/
//     superseded/promoted) + verification_count + evidence kanıtı kullanılır.
//   - topic yazma anında normalize edilir (lowercase, boşluk/_ -> -) — yoksa
//     "auto_threshold" / "auto-threshold" iki ayrı kova olur, search'ün
//     değeri buharlaşır.
//   - evidence[].dirty SUNUCU TARAFINDA hesaplanır (ajan beyanına güvenilmez)
//     — readonly roller (research/judge) worktree açmadan ana checkout'ta
//     çalışır, commit'lenmemiş koda işaret eden kanıt asla "verified"
//     sayılmamalı.
//   - Dokumanlar'a otomatik senkron YOK — knowledge, insan dokümantasyonundan
//     bağımsız bir ajan-bilgisi sistemi (kararlaştırıldı). "promoted" durumu
//     sadece ana oturumun MANUEL kararını kaydetmek için var.

'use strict';
const path = require('path');
const fs = require('fs');
const { execFileSync } = require('child_process');
const { DatabaseSync } = require('node:sqlite');

const REPO_ROOT = process.env.DISPATCH_REPO_ROOT
  ? path.resolve(process.env.DISPATCH_REPO_ROOT)
  : process.cwd();
const KNOWLEDGE_DIR = path.join(REPO_ROOT, '.claude', 'knowledge');
fs.mkdirSync(KNOWLEDGE_DIR, { recursive: true });
const DB_PATH = path.join(KNOWLEDGE_DIR, 'knowledge.db');

const CATEGORIES = ['behavior', 'architecture', 'constraint', 'bug', 'decision'];
const STATUSES = ['candidate', 'verified', 'stale', 'superseded', 'promoted'];
const SCOPES = ['task', 'incidental'];

let db = null;
function getDb() {
  if (db) return db;
  db = new DatabaseSync(DB_PATH);
  db.exec(`
    CREATE TABLE IF NOT EXISTS knowledge (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      topic TEXT NOT NULL,
      category TEXT NOT NULL,
      claim TEXT NOT NULL,
      evidence TEXT NOT NULL DEFAULT '[]',
      scope TEXT NOT NULL DEFAULT 'task',
      commit_sha TEXT,
      source_task TEXT,
      source_role TEXT,
      status TEXT NOT NULL DEFAULT 'candidate',
      verification_count INTEGER NOT NULL DEFAULT 0,
      supporting_tasks TEXT NOT NULL DEFAULT '[]',
      superseded_by INTEGER,
      embedding BLOB,
      created_at TEXT NOT NULL,
      last_verified_commit TEXT,
      last_verified_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge(topic);
    CREATE INDEX IF NOT EXISTS idx_knowledge_status ON knowledge(status);
    CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge(category);

    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
      topic, claim, content='knowledge', content_rowid='id'
    );
    CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
      INSERT INTO knowledge_fts(rowid, topic, claim) VALUES (new.id, new.topic, new.claim);
    END;
    CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
      INSERT INTO knowledge_fts(knowledge_fts, rowid, topic, claim) VALUES('delete', old.id, old.topic, old.claim);
    END;
    CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
      INSERT INTO knowledge_fts(knowledge_fts, rowid, topic, claim) VALUES('delete', old.id, old.topic, old.claim);
      INSERT INTO knowledge_fts(rowid, topic, claim) VALUES (new.id, new.topic, new.claim);
    END;
  `);
  return db;
}

function normalizeTopic(t) {
  return String(t || '')
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
    .replace(/[^a-z0-9.\-]/g, '')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

function getCommitSha(cwd) {
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], { cwd, encoding: 'utf8' }).trim();
  } catch {
    return null;
  }
}

// Bir evidence dosyasının commit'lenmemiş bir değişiklik/untracked içerip
// içermediğini SUNUCU TARAFINDA (ajan beyanına güvenmeden) belirler. Boş
// porcelain çıktısı = dosya HEAD ile temiz, yani kanıt gerçekten o commit'e
// ait.
function isDirty(cwd, file) {
  try {
    const out = execFileSync('git', ['status', '--porcelain', '--', file], { cwd, encoding: 'utf8' });
    return out.trim().length > 0;
  } catch {
    return true; // git hata verirse iyimser olma — dirty say
  }
}

function floatsToBlob(arr) {
  if (!arr) return null;
  const buf = Buffer.from(new Float32Array(arr).buffer);
  return buf;
}
function blobToFloats(buf) {
  if (!buf) return null;
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return Array.from(new Float32Array(ab));
}
function cosine(a, b) {
  let dot = 0;
  for (let i = 0; i < a.length; i++) dot += a[i] * b[i];
  return dot; // bge-m3 çıktısı zaten normalize (norm=1), dot = cosine
}

// evidence: [{file, line}], cwd: RUN_DIR (readonly roller ana checkout, writer
// roller worktree — process.cwd() dispatch.sh'ın `cd "$RUN_DIR"`'ından miras).
function buildEvidence(cwd, evidence) {
  if (!Array.isArray(evidence)) return [];
  return evidence.map((e) => ({
    file: String(e.file || '').trim(),
    line: e.line != null ? Number(e.line) : null,
    dirty: e.file ? isDirty(cwd, e.file) : false,
  }));
}

/**
 * @param {object} args {topic, category, claim, evidence, scope, source_task, source_role, embedding}
 * @param {string} cwd RUN_DIR — commit_sha/dirty hesaplaması buradan
 */
function insertKnowledge(args, cwd) {
  const topic = normalizeTopic(args.topic);
  if (!topic) throw new Error('topic zorunlu (boş/normalize-sonrası-boş olamaz).');
  const category = String(args.category || '').trim();
  if (!CATEGORIES.includes(category)) {
    throw new Error(`category '${category}' geçersiz — şunlardan biri olmalı: ${CATEGORIES.join('|')}`);
  }
  const claim = String(args.claim || '').trim();
  if (!claim) throw new Error('claim zorunlu.');
  const scope = SCOPES.includes(args.scope) ? args.scope : 'task';

  const evidence = buildEvidence(cwd, args.evidence);
  const commitSha = getCommitSha(cwd);
  const embedding = floatsToBlob(args.embedding);

  const database = getDb();
  const stmt = database.prepare(`
    INSERT INTO knowledge
      (topic, category, claim, evidence, scope, commit_sha, source_task, source_role,
       status, verification_count, supporting_tasks, embedding, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', 0, ?, ?, ?)
  `);
  const info = stmt.run(
    topic,
    category,
    claim,
    JSON.stringify(evidence),
    scope,
    commitSha,
    args.source_task || null,
    args.source_role || null,
    JSON.stringify(args.source_task ? [args.source_task] : []),
    embedding,
    new Date().toISOString(),
  );
  return { id: Number(info.lastInsertRowid), topic, commit_sha: commitSha, evidence };
}

// Freshness: bir evidence dosyası knowledge kaydedildiğinden beri değişmiş
// mi? Modelsiz, deterministik — `git log <commit_sha>..HEAD -- <file>` boş
// dönerse dosya o commit'ten beri hiç değişmemiş, kayıt hâlâ taze demektir.
function commitsSinceEvidence(cwd, commitSha, evidence) {
  if (!commitSha || !Array.isArray(evidence) || evidence.length === 0) return null;
  const files = evidence.map((e) => e.file).filter(Boolean);
  if (files.length === 0) return null;
  try {
    const out = execFileSync(
      'git', ['log', '--oneline', `${commitSha}..HEAD`, '--', ...files],
      { cwd, encoding: 'utf8' },
    );
    const lines = out.split('\n').filter(Boolean);
    return lines.length; // 0 = hâlâ taze
  } catch {
    return null; // commit_sha artık repo'da yok (rebase/squash) ya da başka hata — bilinmiyor
  }
}

// FTS5'in varsayılan MATCH semantiği çok kelimeli bir sorgudaki TÜM
// kelimelerin aynı satırda geçmesini şart koşar (implicit AND) — 2026-08-23
// A live test found that multi-word concepts can be split into noisy tokens,
// doğal-dil bir sorgu, kayıtta "failure"/"cascade" geçmediği için sıfır
// sonuç döndürdü, halbuki topic tam eşleşiyordu. Kelimeleri OR ile
// birleştirmek herhangi bir kelimenin eşleşmesini yeterli kılar — BM25
// sıralaması zaten daha çok terim eşleşen satırı öne çıkarır, OR'a
// geçmek doğruluğu değil sadece geri-çağırmayı (recall) artırır.
function buildFtsOrQuery(rawQuery) {
  const terms = String(rawQuery || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((t) => `"${t.replace(/"/g, '')}"`);
  return terms.length ? terms.join(' OR ') : null;
}

/**
 * @param {object} args {query, topic, category, status, limit, queryEmbedding}
 * @param {string} cwd freshness hesaplaması için
 */
function searchKnowledge(args, cwd) {
  const database = getDb();
  const limit = Math.min(Math.max(Number(args.limit) || 10, 1), 50);
  const topicFilter = args.topic ? normalizeTopic(args.topic) : null;
  const category = args.category || null;
  const status = args.status || null;

  // "k." prefix ZORUNLU (2026-08-23 bug fix, canlı testte bulundu): FTS
  // dalı knowledge_fts ile JOIN yapıyor ve o tablo da bir `topic` sütunu
  // taşıyor — prefixsiz "topic LIKE ?" iki tablo arasında belirsiz kalıp
  // "ambiguous column name: topic" hatası fırlatıyordu, dıştaki try/catch
  // bunu yutup sessizce BOŞ SONUÇ döndürüyordu (topic+query birlikte
  // verildiğinde arama sessizce hep sıfır dönüyordu — sadece topic-only ya
  // da query-only ayrı ayrı çalıştığı için önceki testler bunu kaçırdı).
  const where = [];
  const params = [];
  if (topicFilter) { where.push('k.topic LIKE ?'); params.push(`${topicFilter}%`); }
  if (category) { where.push('k.category = ?'); params.push(category); }
  if (status) { where.push('k.status = ?'); params.push(status); }
  else { where.push("k.status != 'superseded'"); } // varsayılan: açıkça istenmedikçe superseded'ı gizle
  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';

  // Filtrelenmiş havuz (SADECE topic/category/status — query DEĞİL): hem
  // BM25 hem cosine bu havuzdan bağımsız aday üretir. POOL_CAP şimdilik
  // sabit — mevcut ölçekte (birkaç yüz kayıt) tüm havuzu cosine ile taramak
  // bedava; ANN indeksi ancak çok daha büyük ölçekte gerekir (SKILL.md'de
  // bilerek ertelendi).
  const POOL_CAP = 500;
  const filteredRows = database
    .prepare(`SELECT * FROM knowledge k ${whereSql} ORDER BY id DESC LIMIT ${POOL_CAP}`)
    .all(...params);

  // 2026-08-24 bug fix (bağımsız model incelemesinde bulundu): eski kod
  // embedding'i sadece BM25'in ürettiği `candidates` üzerinde re-rank
  // olarak kullanıyordu — BM25 sıfır aday döndürürse (kelime örtüşmesi
  // yoksa) embedding'in hiç devreye girme şansı olmuyordu. Canlı kanıt:
  // "trafik almayan servis" (kelime örtüşüyor) 1 sonuç buldu, anlamsal
  // olarak AYNI kaydı tarif eden "hangi mikroservis kimseden istek almıyor
  // boşta duruyor" (kelime örtüşmüyor) 0 sonuç döndürdü — GPU'da embedding
  // hesaplanıyordu ama aramaya hiç katkısı yoktu. Düzeltme: cosine artık
  // TÜM filtrelenmiş havuz üzerinde KENDİ bağımsız sıralamasını üretiyor,
  // RRF iki sıralamanın KESİŞİMİNİ değil BİRLEŞİMİNİ (union) alıyor.
  const bm25Rank = new Map();
  if (args.query && String(args.query).trim()) {
    const ftsQuery = buildFtsOrQuery(args.query);
    try {
      const rows = database.prepare(`
        SELECT k.id, bm25(knowledge_fts) AS bm25_score
        FROM knowledge k JOIN knowledge_fts ON knowledge_fts.rowid = k.id
        WHERE knowledge_fts MATCH ? ${where.length ? 'AND ' + where.join(' AND ') : ''}
        ORDER BY bm25_score LIMIT 100
      `).all(ftsQuery, ...params);
      rows.forEach((r, i) => bm25Rank.set(r.id, i));
    } catch {
      // FTS sözdizimi hatası (özel karakter vb.) — sessizce sıfır BM25 aday,
      // embedding hâlâ kendi havuzunu üretebilir (fail-soft).
    }
  }

  const cosRank = new Map();
  if (args.queryEmbedding) {
    filteredRows
      .map((row) => {
        const emb = blobToFloats(row.embedding);
        return emb ? { id: row.id, sim: cosine(args.queryEmbedding, emb) } : null;
      })
      .filter(Boolean)
      .sort((a, b) => b.sim - a.sim)
      .slice(0, 100) // BM25 ile simetrik üst sınır
      .forEach((x, i) => cosRank.set(x.id, i));
  }

  // "Arama denendi ama sıfır eşleşme" ile "hiç arama istenmedi" AYRI
  // tutulmalı (2026-08-24, kendi düzeltmemi test ederken bulundu — ilk
  // versiyon bm25Rank/cosRank ikisi de boşsa "sorgu verilmedi" varsayıp
  // TÜM veritabanını döndürüyordu; gerçek bir sorgu hiçbir şeyle eşleşmezse
  // bu YANLIŞ — boş sonuç dönmeli, tüm tabloya düşmemeli).
  const searchAttempted = Boolean(args.query && String(args.query).trim()) || Boolean(args.queryEmbedding);
  const rowById = new Map(filteredRows.map((r) => [r.id, r]));
  let orderedIds;
  if (!searchAttempted) {
    // Ne query ne queryEmbedding verildi — salt topic/category/status
    // filtresiyle "gözat" modu, filtrelenmiş havuzu id DESC döndür.
    orderedIds = filteredRows.map((r) => r.id);
  } else {
    const unionIds = new Set([...bm25Rank.keys(), ...cosRank.keys()]);
    orderedIds = [...unionIds]
      .map((id) => ({
        id,
        rrf: 1 / (60 + (bm25Rank.get(id) ?? 10000)) + 1 / (60 + (cosRank.get(id) ?? 10000)),
      }))
      .sort((a, b) => b.rrf - a.rrf)
      .map((x) => x.id);
  }

  const ranked = orderedIds.map((id) => rowById.get(id)).filter(Boolean);

  return ranked.slice(0, limit).map((row) => {
    const evidence = JSON.parse(row.evidence || '[]');
    const commits_since_evidence = commitsSinceEvidence(cwd, row.commit_sha, evidence);
    return {
      id: row.id,
      topic: row.topic,
      category: row.category,
      claim: row.claim,
      evidence,
      scope: row.scope,
      status: row.status,
      commit_sha: row.commit_sha,
      source_task: row.source_task,
      source_role: row.source_role,
      verification_count: row.verification_count,
      created_at: row.created_at,
      stale_warning: commits_since_evidence == null
        ? null
        : commits_since_evidence > 0
          ? `⚠ evidence bu kayıttan beri ${commits_since_evidence} commit değişmiş, doğrula`
          : null,
    };
  });
}

module.exports = { getDb, normalizeTopic, insertKnowledge, searchKnowledge, CATEGORIES, STATUSES, SCOPES };
