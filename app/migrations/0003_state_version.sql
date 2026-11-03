-- The browser's saved-format version (STATE_VERSION in ELiDDI's persistence.js),
-- stored with the snapshot so a browser can tell whether it understands it
-- (ELiDDI docs/adr/0007). The server never reads the state itself.
ALTER TABLE diary_states ADD COLUMN state_version INTEGER NOT NULL DEFAULT 1;
