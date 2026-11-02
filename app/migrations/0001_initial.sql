-- A person who takes part in the study. Login codes are never stored, only
-- their hash. The id is random and opaque: it is returned at login and the
-- browser uses it to key its local copy of the diary (ELiDDI#205).
CREATE TABLE respondents (
    id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- The in-progress state of a Respondent, as the browser persists it, so it can
-- follow them between devices. revision goes up on every save and lets the
-- server refuse a write made from an out-of-date copy.
CREATE TABLE diary_states (
    respondent_id TEXT PRIMARY KEY REFERENCES respondents (id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- A Diary sent in through POST /submit, kept exactly as received (docs/adr/0006
-- in the ELiDDI repo). A Diary can be submitted more than once, so there is one
-- row per submission.
CREATE TABLE submissions (
    id INTEGER PRIMARY KEY,
    respondent_id TEXT NOT NULL REFERENCES respondents (id),
    experiment_id TEXT NOT NULL,
    date TEXT NOT NULL,
    status INTEGER NOT NULL,
    payload TEXT NOT NULL,
    submitted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX submissions_by_respondent ON submissions (respondent_id, date);
