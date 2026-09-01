CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    batch_key TEXT NOT NULL,
    batch_source TEXT NOT NULL,
    seed INTEGER NOT NULL,
    matched INTEGER NOT NULL,
    exception_count INTEGER NOT NULL,
    match_rate REAL NOT NULL,
    baseline_match_rate REAL,
    precision REAL,
    recall REAL,
    f1 REAL,
    false_positives INTEGER,
    false_negatives INTEGER,
    closed_bank_net TEXT NOT NULL,
    in_flight_gross TEXT NOT NULL,
    llm_used INTEGER NOT NULL,
    model TEXT,
    auto_closed_by_rules INTEGER NOT NULL DEFAULT 0,
    auto_closed_by_llm INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_batch_key ON runs(batch_key);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);

CREATE TABLE IF NOT EXISTS run_exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    exception_id TEXT NOT NULL,
    exception_key TEXT NOT NULL,
    exception_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    refs TEXT NOT NULL,
    amount_at_risk TEXT NOT NULL,
    confidence REAL,
    hypothesis_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_run_exceptions_key ON run_exceptions(exception_key);
CREATE INDEX IF NOT EXISTS idx_run_exceptions_run ON run_exceptions(run_id);

CREATE TABLE IF NOT EXISTS run_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    match_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    reason TEXT NOT NULL,
    refs TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES runs(id),
    at TEXT NOT NULL,
    exception_id TEXT,
    actor TEXT NOT NULL,
    event TEXT NOT NULL,
    validator_passed INTEGER,
    proposed_record_ids TEXT,
    evidence TEXT,
    rationale TEXT,
    payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id);

CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TABLE IF NOT EXISTS exception_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_key TEXT NOT NULL,
    exception_key TEXT NOT NULL,
    author TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    assignee TEXT NOT NULL DEFAULT '',
    resolved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notes_batch_key ON exception_notes(batch_key, exception_key);
