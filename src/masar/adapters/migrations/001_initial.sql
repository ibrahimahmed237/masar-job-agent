CREATE TABLE postings (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  external_id TEXT,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  location TEXT,
  text TEXT NOT NULL,
  checksum TEXT NOT NULL UNIQUE,
  fetched_at TEXT NOT NULL
);
CREATE UNIQUE INDEX postings_external ON postings (source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE jobs (
  posting_id INTEGER PRIMARY KEY REFERENCES postings (id),
  status TEXT NOT NULL CHECK (status IN ('assessed', 'screened', 'unreadable', 'failed')),
  job TEXT,
  findings TEXT NOT NULL,
  flags TEXT NOT NULL,
  assessment TEXT,
  score INTEGER,
  recommendation TEXT,
  career_checksum TEXT,
  assessed_at TEXT NOT NULL
);

CREATE TABLE documents (
  id INTEGER PRIMARY KEY,
  posting_id INTEGER NOT NULL REFERENCES postings (id),
  kind TEXT NOT NULL,
  language TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'failed')),
  markdown TEXT NOT NULL,
  blocks TEXT NOT NULL,
  dropped TEXT NOT NULL,
  warnings TEXT NOT NULL,
  judged INTEGER NOT NULL,
  edited INTEGER NOT NULL,
  reason TEXT,
  run_id TEXT NOT NULL,
  career_checksum TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE INDEX documents_posting ON documents (posting_id);

CREATE TABLE applications (
  posting_id INTEGER PRIMARY KEY REFERENCES postings (id),
  state TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE application_events (
  id INTEGER PRIMARY KEY,
  posting_id INTEGER NOT NULL REFERENCES postings (id),
  from_state TEXT,
  to_state TEXT NOT NULL,
  note TEXT,
  at TEXT NOT NULL
);
CREATE INDEX application_events_posting ON application_events (posting_id);

CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  posting_id INTEGER REFERENCES postings (id),
  status TEXT NOT NULL,
  reason TEXT,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE TABLE run_steps (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs (id),
  ordinal INTEGER NOT NULL,
  step TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  tokens_in INTEGER NOT NULL,
  tokens_out INTEGER NOT NULL,
  duration_ms INTEGER NOT NULL,
  input_checksum TEXT NOT NULL,
  output TEXT NOT NULL
);
CREATE INDEX run_steps_run ON run_steps (run_id);

CREATE TABLE usage_daily (
  day TEXT PRIMARY KEY,
  tokens INTEGER NOT NULL
);
