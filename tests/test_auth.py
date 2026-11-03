from datetime import datetime, timedelta, timezone

import pytest

from app import auth, codes, create_app, db, respondents

CODE = 'ABCDEFGH'


@pytest.fixture
def app(tmp_path):
    app = create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')
    conn = db.connect(app.config['DATABASE'])
    app.respondent_id = respondents.create_respondent(conn, CODE, app.config['CODE_HASH_KEY'])
    conn.close()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def query(app, sql, args=()):
    conn = db.connect(app.config['DATABASE'])
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def login(client, code=CODE, **kwargs):
    return client.post('/login', json={'code': code}, **kwargs)


def bearer(token):
    return {'Authorization': f'Bearer {token}'}


def set_time(monkeypatch, moment):
    monkeypatch.setattr(auth, 'utcnow', lambda: moment)


# ---- login

def test_valid_code_returns_a_token_and_the_respondent_id(client, app):
    response = login(client)

    assert response.status_code == 200
    body = response.get_json()
    assert body['respondentId'] == app.respondent_id
    assert len(body['token']) >= 40
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('typed', ['abcd-efgh', ' abcd efgh ', 'AbCdEfGh'])
def test_code_may_be_typed_loosely(client, typed):
    assert login(client, typed).status_code == 200


def test_expiry_follows_the_configured_lifetime(client, app, monkeypatch):
    now = datetime(2026, 11, 3, 9, 0, 0, tzinfo=timezone.utc)
    set_time(monkeypatch, now)
    app.config['TOKEN_LIFETIME'] = 600

    assert login(client).get_json()['expiresAt'] == '2026-11-03T09:10:00Z'


def test_default_lifetime_is_twelve_hours(app):
    assert app.config['TOKEN_LIFETIME'] == 12 * 60 * 60


def test_lifetime_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('ELIDDI_TOKEN_LIFETIME', '90')

    assert create_app(data_dir=tmp_path / 'd', database=tmp_path / 'x.sqlite3').config['TOKEN_LIFETIME'] == 90


def test_the_token_is_stored_hashed(client, app):
    token = login(client).get_json()['token']

    rows = query(app, 'SELECT * FROM tokens')
    assert len(rows) == 1
    assert token not in tuple(rows[0])
    assert rows[0]['token_hash'] == auth.hash_token(token)


def test_each_login_gets_its_own_token(client):
    assert login(client).get_json()['token'] != login(client).get_json()['token']


@pytest.mark.parametrize('code', ['ZZZZZZZZ', 'ABCDEFG', 'ABCDEFGHJ', '', '   '])
def test_wrong_code_is_refused_the_same_way(client, code):
    response = login(client, code)

    assert response.status_code == 401
    assert response.get_json() == {'error': 'invalid code'}


def test_wrong_code_issues_no_token(client, app):
    login(client, 'ZZZZZZZZ')

    assert query(app, 'SELECT * FROM tokens') == []


@pytest.mark.parametrize('body', [{}, {'code': 5}, {'code': None}, [], 'x'])
def test_malformed_body_is_a_400(client, body):
    assert client.post('/login', json=body).status_code == 400


def test_non_json_body_is_a_400(client):
    assert client.post('/login', data='code=ABCDEFGH', content_type='text/plain').status_code == 400


# ---- protected routes

def test_logout_needs_a_token(client):
    response = client.post('/logout')

    assert response.status_code == 401
    assert response.headers['WWW-Authenticate'] == 'Bearer'


@pytest.mark.parametrize('header', ['Bearer', 'Bearer ', 'Basic abc', 'abc', 'Bearer nonsense'])
def test_invalid_authorization_headers_are_refused(client, header):
    assert client.post('/logout', headers={'Authorization': header}).status_code == 401


def test_logout_ends_that_login_only(client):
    first = login(client).get_json()['token']
    second = login(client).get_json()['token']

    assert client.post('/logout', headers=bearer(first)).status_code == 204

    assert client.post('/logout', headers=bearer(first)).status_code == 401
    assert client.post('/logout', headers=bearer(second)).status_code == 204


def test_expired_token_is_refused_and_removed(client, app, monkeypatch):
    now = datetime(2026, 11, 3, 9, 0, 0, tzinfo=timezone.utc)
    set_time(monkeypatch, now)
    token = login(client).get_json()['token']

    set_time(monkeypatch, now + timedelta(seconds=app.config['TOKEN_LIFETIME'] + 1))

    assert client.post('/logout', headers=bearer(token)).status_code == 401
    assert query(app, 'SELECT * FROM tokens') == []


def test_token_still_works_just_before_it_expires(client, app, monkeypatch):
    now = datetime(2026, 11, 3, 9, 0, 0, tzinfo=timezone.utc)
    set_time(monkeypatch, now)
    token = login(client).get_json()['token']

    set_time(monkeypatch, now + timedelta(seconds=app.config['TOKEN_LIFETIME'] - 1))

    assert client.post('/logout', headers=bearer(token)).status_code == 204


def test_login_clears_out_expired_tokens(client, app, monkeypatch):
    now = datetime(2026, 11, 3, 9, 0, 0, tzinfo=timezone.utc)
    set_time(monkeypatch, now)
    login(client)

    set_time(monkeypatch, now + timedelta(days=2))
    login(client)

    assert len(query(app, 'SELECT * FROM tokens')) == 1


def test_require_auth_gives_the_view_the_respondent(app, client):
    @app.get('/whoami')
    @auth.require_auth
    def whoami():
        from flask import g

        return g.respondent_id

    token = login(client).get_json()['token']

    assert client.get('/whoami', headers=bearer(token)).get_data(as_text=True) == app.respondent_id
    assert client.get('/whoami').status_code == 401


def test_deleting_a_respondent_removes_their_tokens(client, app):
    login(client)

    conn = db.connect(app.config['DATABASE'])
    conn.execute('DELETE FROM respondents WHERE id = ?', (app.respondent_id,))
    conn.close()

    assert query(app, 'SELECT * FROM tokens') == []


# ---- rate limiting

def fail(client, times, **kwargs):
    for _ in range(times):
        assert login(client, 'ZZZZZZZZ', **kwargs).status_code == 401


def test_too_many_failures_block_that_client(client, app):
    fail(client, app.config['LOGIN_MAX_FAILURES'])

    response = login(client, 'ZZZZZZZZ')

    assert response.status_code == 429
    assert int(response.headers['Retry-After']) > 0


def test_a_blocked_client_cannot_log_in_even_with_the_right_code(client, app):
    fail(client, app.config['LOGIN_MAX_FAILURES'])

    assert login(client).status_code == 429


def test_blocked_attempts_are_not_counted_again(client, app):
    fail(client, app.config['LOGIN_MAX_FAILURES'])
    login(client, 'ZZZZZZZZ')
    login(client, 'ZZZZZZZZ')

    assert query(app, 'SELECT COUNT(*) AS n FROM login_failures')[0]['n'] == app.config['LOGIN_MAX_FAILURES']


def test_failures_below_the_limit_do_not_block(client, app):
    fail(client, app.config['LOGIN_MAX_FAILURES'] - 1)

    assert login(client).status_code == 200


def test_other_clients_are_not_blocked(client, app):
    fail(client, app.config['LOGIN_MAX_FAILURES'])

    assert login(client, environ_overrides={'REMOTE_ADDR': '10.9.9.9'}).status_code == 200


def test_successful_logins_do_not_count_against_the_limit(client, app):
    for _ in range(app.config['LOGIN_MAX_FAILURES'] + 2):
        assert login(client).status_code == 200


def test_the_block_lifts_when_the_failures_age_out(client, app, monkeypatch):
    now = datetime(2026, 11, 3, 9, 0, 0, tzinfo=timezone.utc)
    set_time(monkeypatch, now)
    fail(client, app.config['LOGIN_MAX_FAILURES'])
    assert login(client).status_code == 429

    set_time(monkeypatch, now + timedelta(seconds=app.config['LOGIN_WINDOW'] + 1))

    assert login(client).status_code == 200


def test_retry_after_counts_down_to_the_oldest_failure_leaving_the_window(client, app, monkeypatch):
    now = datetime(2026, 11, 3, 9, 0, 0, tzinfo=timezone.utc)
    set_time(monkeypatch, now)
    app.config['LOGIN_WINDOW'] = 600
    fail(client, app.config['LOGIN_MAX_FAILURES'])

    set_time(monkeypatch, now + timedelta(seconds=100))

    assert int(login(client).headers['Retry-After']) in range(500, 502)


def test_limit_and_window_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('ELIDDI_LOGIN_MAX_FAILURES', '3')
    monkeypatch.setenv('ELIDDI_LOGIN_WINDOW', '60')

    app = create_app(data_dir=tmp_path / 'd', database=tmp_path / 'x.sqlite3')

    assert (app.config['LOGIN_MAX_FAILURES'], app.config['LOGIN_WINDOW']) == (3, 60)


def test_forwarded_for_is_ignored_unless_proxies_are_configured(client, app):
    fail(client, app.config['LOGIN_MAX_FAILURES'], headers={'X-Forwarded-For': '1.1.1.1'})

    # a spoofed address does not get a fresh allowance
    assert login(client, headers={'X-Forwarded-For': '2.2.2.2'}).status_code == 429


def test_behind_a_proxy_clients_are_told_apart_by_forwarded_for(tmp_path, monkeypatch):
    monkeypatch.setenv('ELIDDI_PROXY_HOPS', '1')
    app = create_app(data_dir=tmp_path / 'd', database=tmp_path / 'x.sqlite3')
    conn = db.connect(app.config['DATABASE'])
    respondents.create_respondent(conn, CODE, app.config['CODE_HASH_KEY'])
    conn.close()
    client = app.test_client()

    fail(client, app.config['LOGIN_MAX_FAILURES'], headers={'X-Forwarded-For': '1.1.1.1'})

    assert login(client, headers={'X-Forwarded-For': '1.1.1.1'}).status_code == 429
    assert login(client, headers={'X-Forwarded-For': '2.2.2.2'}).status_code == 200


# ---- CORS

def test_preflight_for_login_allows_the_authorization_header(client):
    response = client.options('/login')

    assert response.status_code in (200, 204)
    assert 'Authorization' in response.headers['Access-Control-Allow-Headers']
    assert 'Content-Type' in response.headers['Access-Control-Allow-Headers']


def test_retry_after_is_readable_by_the_page(client):
    assert 'Retry-After' in login(client).headers['Access-Control-Expose-Headers']


def test_login_response_has_the_cors_header(client):
    assert login(client).headers['Access-Control-Allow-Origin'] == '*'
