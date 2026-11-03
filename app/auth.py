import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request

from . import codes, db

auth = Blueprint('auth', __name__)

TIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'  # sorts as text, so SQL can compare it


def utcnow():
    return datetime.now(timezone.utc)


def to_text(moment):
    return moment.strftime(TIME_FORMAT)


def hash_token(token):
    # the token is 256 random bits, so a plain hash is enough (unlike a code)
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(conn, respondent_id):
    token = secrets.token_urlsafe(32)
    now = utcnow()
    expires = now + timedelta(seconds=current_app.config['TOKEN_LIFETIME'])
    conn.execute(
        'INSERT INTO tokens (token_hash, respondent_id, created_at, expires_at) VALUES (?, ?, ?, ?)',
        (hash_token(token), respondent_id, to_text(now), to_text(expires)),
    )
    return token, to_text(expires)


# Seconds until this client may try again, or 0 if it may try now
def seconds_until_allowed(conn, ip):
    window = timedelta(seconds=current_app.config['LOGIN_WINDOW'])
    since = to_text(utcnow() - window)
    conn.execute('DELETE FROM login_failures WHERE failed_at <= ?', (since,))
    failures = conn.execute(
        'SELECT failed_at FROM login_failures WHERE ip = ? ORDER BY failed_at', (ip,)
    ).fetchall()
    limit = current_app.config['LOGIN_MAX_FAILURES']
    if len(failures) < limit:
        return 0
    # allowed again when enough old failures have aged out of the window
    blocking = datetime.strptime(failures[len(failures) - limit]['failed_at'], TIME_FORMAT).replace(
        tzinfo=timezone.utc
    )
    return max(1, int((blocking + window - utcnow()).total_seconds()) + 1)


# Every way of being wrong (unknown code, wrong length, empty) answers the same
# way, so a response says nothing about how close a guess was
@auth.post('/login')
def login():
    body = request.get_json(silent=True)
    code = body.get('code') if isinstance(body, dict) else None
    if not isinstance(code, str):
        return jsonify(error='body must be a JSON object with a "code"'), 400

    conn = db.get_db()
    ip = request.remote_addr or 'unknown'

    wait = seconds_until_allowed(conn, ip)
    if wait:
        response = jsonify(error='too many failed attempts, try again later')
        response.headers['Retry-After'] = str(wait)
        return response, 429

    # The code is looked up by its keyed hash. The attacker cannot compute that
    # hash without the key, so how long the lookup takes tells them nothing.
    code_hash = codes.hash_code(code, current_app.config['CODE_HASH_KEY'])
    respondent = conn.execute('SELECT id FROM respondents WHERE code_hash = ?', (code_hash,)).fetchone()
    if respondent is None:
        conn.execute('INSERT INTO login_failures (ip, failed_at) VALUES (?, ?)', (ip, to_text(utcnow())))
        return jsonify(error='invalid code'), 401

    with db.transaction(conn):
        conn.execute('DELETE FROM tokens WHERE expires_at <= ?', (to_text(utcnow()),))
        token, expires_at = issue_token(conn, respondent['id'])

    response = jsonify(token=token, respondentId=respondent['id'], expiresAt=expires_at)
    response.headers['Cache-Control'] = 'no-store'
    return response


def unauthorized():
    response = jsonify(error='login required')
    response.headers['WWW-Authenticate'] = 'Bearer'
    return response, 401


# Protects a route: needs "Authorization: Bearer <token>" with a token that is
# known and not expired. The route can then read g.respondent_id (and
# g.token_hash, to end this login).
def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        scheme, _, token = request.headers.get('Authorization', '').partition(' ')
        if scheme.lower() != 'bearer' or not token.strip():
            return unauthorized()
        token_hash = hash_token(token.strip())
        row = db.get_db().execute(
            'SELECT respondent_id, expires_at FROM tokens WHERE token_hash = ?', (token_hash,)
        ).fetchone()
        if row is None:
            return unauthorized()
        if row['expires_at'] <= to_text(utcnow()):
            db.get_db().execute('DELETE FROM tokens WHERE token_hash = ?', (token_hash,))
            return unauthorized()
        g.respondent_id = row['respondent_id']
        g.token_hash = token_hash
        return view(*args, **kwargs)

    return wrapped


# Ends this login only: the Respondent's other devices stay logged in
@auth.post('/logout')
@require_auth
def logout():
    db.get_db().execute('DELETE FROM tokens WHERE token_hash = ?', (g.token_hash,))
    return '', 204
