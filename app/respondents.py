import json
import uuid

from . import codes, db


# The id is random and opaque, not a counter: it goes to the browser at login
# and reveals nothing about how many Respondents there are
def create_respondent(conn, code, key):
    respondent_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO respondents (id, code_hash) VALUES (?, ?)',
        (respondent_id, codes.hash_code(code, key)),
    )
    return respondent_id


# TEST PHASE ONLY. Lausanne has not decided how real codes get issued (probably
# email), so for now the server makes a few dummy Respondents whose codes
# are logged at start-up, standing in for that email.
#
# The codes are kept in <state_dir>/dummy_codes.json, so a restart logs the same
# codes instead of making new ones. That file holds them in plain text: it is
# a development convenience and must not exist in production, where
# ELIDDI_DUMMY_RESPONDENTS is left at 0.
#
# -> the list of `count` codes
def ensure_dummy_respondents(conn, state_dir, count, key, length, alphabet):
    path = state_dir / 'dummy_codes.json'
    stored = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

    while len(stored) < count:
        code = codes.generate_code(length, alphabet)
        if code not in stored:  # codes must be unique
            stored.append(code)

    chosen = stored[:count]
    with db.transaction(conn):
        for code in chosen:
            exists = conn.execute(
                'SELECT 1 FROM respondents WHERE code_hash = ?', (codes.hash_code(code, key),)
            ).fetchone()
            if not exists:
                create_respondent(conn, code, key)

    state_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored, indent=2), encoding='utf-8')
    return chosen
