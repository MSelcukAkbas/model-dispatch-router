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
 * @param {object} args {topic, category, claim, evidence, scope, source_task, source_role}
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

  const database = getDb();
  const stmt = database.prepare(`
    INSERT INTO knowledge
      (topic, category, claim, evidence, scope, commit_sha, source_task, source_role,
       status, verification_count, supporting_tasks, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', 0, ?, ?)
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
// kelimelerin aynı satırda geçmesini şart koşar (implicit AND) —
// Kelimeleri OR ile birleştirmek herhangi bir kelimenin eşleşmesini yeterli kılar.
function buildFtsOrQuery(rawQuery) {
  const terms = String(rawQuery || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((t) => `"${t.replace(/"/g, '')}"`);
  return terms.length ? terms.join(' OR ') : null;
}

/**
 * @param {object} args {query, topic, category, status, limit}
 * @param {string} cwd freshness hesaplaması için
 */
function searchKnowledge(args, cwd) {
  const database = getDb();
  const limit = Math.min(Math.max(Number(args.limit) || 10, 1), 50);
  const topicFilter = args.topic ? normalizeTopic(args.topic) : null;
  const category = args.category || null;
  const status = args.status || null;

  const where = [];
  const params = [];
  if (topicFilter) { where.push('k.topic LIKE ?'); params.push(`${topicFilter}%`); }
  if (category) { where.push('k.category = ?'); params.push(category); }
  if (status) { where.push('k.status = ?'); params.push(status); }
  else { where.push("k.status != 'superseded'"); } // varsayılan: açıkça istenmedikçe superseded'ı gizle

  let rows = [];
  const searchAttempted = Boolean(args.query && String(args.query).trim());

  if (searchAttempted) {
    const ftsQuery = buildFtsOrQuery(args.query);
    if (ftsQuery) {
      try {
        const whereSql = where.length ? 'AND ' + where.join(' AND ') : '';
        rows = database.prepare(`
          SELECT k.*, bm25(knowledge_fts) AS bm25_score
          FROM knowledge k JOIN knowledge_fts ON knowledge_fts.rowid = k.id
          WHERE knowledge_fts MATCH ? ${whereSql}
          ORDER BY bm25_score LIMIT ?
        `).all(ftsQuery, ...params, limit);
      } catch {
        // FTS sözdizimi hatası durumunda boş dön
        rows = [];
      }
    }
  } else {
    // Salt filtreli gözat (browse) modu
    const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';
    rows = database.prepare(`
      SELECT k.* FROM knowledge k ${whereSql} ORDER BY id DESC LIMIT ?
    `).all(...params, limit);
  }

  return rows.map((row) => {
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
