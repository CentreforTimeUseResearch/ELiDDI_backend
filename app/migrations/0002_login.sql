-- A login. Only the SHA-256 of the bearer token is kept, so a copy of the
-- database cannot be used to act as a Respondent. A token stops working at
-- expires_at, or when it is deleted (logout).
CREATE TABLE tokens (
    token_hash TEXT PRIMARY KEY,
    respondent_id TEXT NOT NULL REFERENCES respondents (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at TEXT NOT NULL
);

CREATE INDEX tokens_by_respondent ON tokens (respondent_id);

-- Failed login attempts, per client address, for rate limiting. Kept in the
-- database rather than in memory so the limit holds across several workers.
CREATE TABLE login_failures (
    id INTEGER PRIMARY KEY,
    ip TEXT NOT NULL,
    failed_at TEXT NOT NULL
);

CREATE INDEX login_failures_by_ip ON login_failures (ip, failed_at);
