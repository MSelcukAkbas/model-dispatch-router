-- AgentMind kernel schema (L0 event log + L1 join tables).
--
-- PRAGMAs are set in store.py, not here — same split agentic-ssh-mcp's
-- app/db/schema.sql + database.py use.

-- L0: the append-only event stream. Every component writes here; nothing
-- updates or deletes a row. `payload_json` is deliberately schemaless so a
-- new producer never needs a migration to start emitting.
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    task_id      TEXT,
    run_id       TEXT,
    actor        TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);

-- Derived current-state view of a dispatch. Columns mirror the key=value
-- pairs dispatch.sh writes to .agent-logs/<task>.meta, plus the .attempt and
-- .diffstat sidecar files it keeps next to them.
CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    role         TEXT,
    model        TEXT,
    -- 'claude' (dispatch.sh) or 'agy' (dispatch-agy.sh). The two write
    -- different .meta shapes; agy names its real model, claude does not.
    engine       TEXT,
    account      TEXT,
    effort       TEXT,
    budget_usd   REAL,
    attempt      INTEGER,
    diffstat     INTEGER,
    session_id   TEXT,
    no_worktree  INTEGER,
    config_dir   TEXT,
    status       TEXT,
    -- Approximated from the .meta file's mtime on import: dispatch.sh does not
    -- record a dispatch timestamp of its own. Rows created by `am event` carry
    -- a real timestamp instead. `started_at_exact` says which it is.
    started_at   TEXT,
    started_at_exact INTEGER NOT NULL DEFAULT 0,
    finished_at  TEXT,
    source       TEXT NOT NULL DEFAULT 'import'
);
CREATE INDEX IF NOT EXISTS idx_tasks_role    ON tasks(role);
CREATE INDEX IF NOT EXISTS idx_tasks_account ON tasks(account);

-- Mirror of knowledge.db's `knowledge` table. The status lifecycle
-- (candidate/verified/stale/superseded/promoted), verification_count,
-- supporting_tasks and superseded_by are kept verbatim — that vocabulary is
-- already in production in knowledge-store.js and is not re-invented here.
-- `embedding` is intentionally not carried over in Phase 0.
CREATE TABLE IF NOT EXISTS claims (
    id                    INTEGER PRIMARY KEY,
    topic                 TEXT NOT NULL,
    category              TEXT NOT NULL,
    claim                 TEXT NOT NULL,
    evidence_json         TEXT NOT NULL DEFAULT '[]',
    scope                 TEXT NOT NULL DEFAULT 'task',
    commit_sha            TEXT,
    source_task           TEXT,
    source_role           TEXT,
    status                TEXT NOT NULL DEFAULT 'candidate',
    verification_count    INTEGER NOT NULL DEFAULT 0,
    supporting_tasks_json TEXT NOT NULL DEFAULT '[]',
    superseded_by         INTEGER,
    created_at            TEXT NOT NULL,
    last_verified_commit  TEXT,
    last_verified_at      TEXT,
    origin                TEXT NOT NULL DEFAULT 'import'
);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_claims_topic  ON claims(topic);
CREATE INDEX IF NOT EXISTS idx_claims_task   ON claims(source_task);

-- L1 join table, populated in Phase 1: one row per claim evidence entry,
-- carrying the graphify node it resolves to. `dangling=1` means the evidence
-- points at a file/line graphify has no node for any more — a signal that the
-- code moved, not an error to swallow.
CREATE TABLE IF NOT EXISTS node_refs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id      INTEGER NOT NULL REFERENCES claims(id),
    evidence_idx  INTEGER NOT NULL,
    file          TEXT NOT NULL,
    line          INTEGER,
    graph_node_id TEXT,
    resolved_at   TEXT,
    dangling      INTEGER NOT NULL DEFAULT 0,
    -- Why a ref did not resolve. 'resolved' | 'file_missing' (the cited path is
    -- gone — the code really moved) | 'not_extracted' (the file is there but no
    -- extractor covers it, e.g. .yaml). Collapsing these into one "dangling"
    -- number made a tooling gap look like code drift.
    reason        TEXT NOT NULL DEFAULT 'resolved',
    UNIQUE(claim_id, evidence_idx)
);
CREATE INDEX IF NOT EXISTS idx_node_refs_file ON node_refs(file);
CREATE INDEX IF NOT EXISTS idx_node_refs_node ON node_refs(graph_node_id);

-- The code graph, extracted by graphify and persisted here so overlay queries
-- never need graphify at runtime — only `am graph build` does. Node ids are
-- graphify's own; `source_line` is source_location parsed to an int (NULL for
-- the file-level nodes that carry no line anchor).
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id     TEXT NOT NULL,
    repo        TEXT NOT NULL DEFAULT '',
    label       TEXT,
    source_file TEXT,
    source_line INTEGER,
    node_kind   TEXT,
    file_type   TEXT,
    built_at    TEXT,
    PRIMARY KEY (repo, node_id)
);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_file ON graph_nodes(repo, source_file);

CREATE TABLE IF NOT EXISTS graph_edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo        TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL,
    target      TEXT NOT NULL,
    relation    TEXT,
    confidence  TEXT,
    source_file TEXT,
    source_line INTEGER,
    UNIQUE(repo, source, target, relation)
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(repo, source);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(repo, target);
