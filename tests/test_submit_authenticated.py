import json
from datetime import timedelta

import pytest

from app import auth, create_app, db, respondents

CODE = 'ABCDEFGH'
PAYLOAD = {
    'experimentID': 'stratus',
    'version': '1.0',
    'dayBoundary': '04:00',
    'date': '2026-10-28',
    'status': 100,
    'timelines': [[{'id': 'a', 'startOffsetMins': 0, 'endOffsetMins': 1440, 'activity': 'Sleep'}]],
}


def make_app(tmp_path):
    app = create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')
    conn = db.connect(app.config['DATABASE'])
    app.respondent_id = respondents.create_respondent(conn, CODE, app.config['CODE_HASH_KEY'])
    conn.close()
    return app


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


@pytest.fixture
def client(app):
    return app.test_client()


def bearer(client, code=CODE):
    token = client.post('/login', json={'code': code}).get_json()['token']
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def headers(client):
    return bearer(client)


def rows(app):
    conn = db.connect(app.config['DATABASE'])
    try:
        return conn.execute('SELECT * FROM submissions ORDER BY id').fetchall()
    finally:
        conn.close()


def files(app):
    folder = app.config['DATA_DIR']
    return list(folder.rglob('*.json')) if folder.exists() else []


def test_a_token_stores_the_diary_in_the_database(client, app, headers):
    response = client.post('/submit', json=PAYLOAD, headers=headers)

    assert response.status_code == 201
    [row] = rows(app)
    assert response.get_json() == {'id': row['id']}
    assert row['respondent_id'] == app.respondent_id
    assert (row['experiment_id'], row['date'], row['status']) == ('stratus', '2026-10-28', 100)
    assert json.loads(row['payload']) == PAYLOAD
    assert row['submitted_at']


def test_a_token_writes_no_file(client, app, headers):
    client.post('/submit', json=PAYLOAD, headers=headers)

    assert files(app) == []


def test_submitting_again_adds_another_row(client, app, headers):
    client.post('/submit', json=PAYLOAD, headers=headers)
    client.post('/submit', json={**PAYLOAD, 'status': 0}, headers=headers)

    assert [r['status'] for r in rows(app)] == [100, 0]


def test_each_respondent_gets_their_own_rows(tmp_path):
    app = make_app(tmp_path)
    conn = db.connect(app.config['DATABASE'])
    other = respondents.create_respondent(conn, 'ZZZZZZZZ', app.config['CODE_HASH_KEY'])
    conn.close()
    client = app.test_client()
    for code in (CODE, 'ZZZZZZZZ'):
        client.post('/submit', json=PAYLOAD, headers=bearer(client, code))

    assert sorted(r['respondent_id'] for r in rows(app)) == sorted([app.respondent_id, other])


@pytest.mark.parametrize('header', ['Bearer nonsense', 'Bearer', 'Basic abc'])
def test_a_bad_token_is_refused_not_treated_as_no_token(client, app, header):
    response = client.post('/submit', json=PAYLOAD, headers={'Authorization': header})

    assert response.status_code == 401
    assert response.headers['WWW-Authenticate'] == 'Bearer'
    assert rows(app) == [] and files(app) == []


def test_an_expired_token_is_refused(client, app, headers, monkeypatch):
    real_now = auth.utcnow
    monkeypatch.setattr(auth, 'utcnow', lambda: real_now() + timedelta(seconds=app.config['TOKEN_LIFETIME'] + 1))

    assert client.post('/submit', json=PAYLOAD, headers=headers).status_code == 401
    assert rows(app) == []


@pytest.mark.parametrize('status', [None, 'x', 50, True, 1])
def test_status_must_be_0_or_100_when_stored(client, app, headers, status):
    assert client.post('/submit', json={**PAYLOAD, 'status': status}, headers=headers).status_code == 400
    assert rows(app) == []


def test_the_payload_is_still_validated(client, app, headers):
    assert client.post('/submit', json={**PAYLOAD, 'date': '2026-13-45'}, headers=headers).status_code == 400
    assert client.post('/submit', json={**PAYLOAD, 'experimentID': '../x'}, headers=headers).status_code == 400
    assert client.post('/submit', json=[], headers=headers).status_code == 400
    assert rows(app) == []


# ---- ELIDDI_REQUIRE_AUTH

@pytest.fixture
def strict(tmp_path, monkeypatch):
    monkeypatch.setenv('ELIDDI_REQUIRE_AUTH', '1')
    return make_app(tmp_path)


def test_without_the_setting_no_token_still_saves_a_file(client, app):
    assert client.post('/submit', json=PAYLOAD).status_code == 201
    assert len(files(app)) == 1 and rows(app) == []


def test_required_auth_refuses_a_request_without_a_token(strict):
    response = strict.test_client().post('/submit', json=PAYLOAD)

    assert response.status_code == 401
    assert files(strict) == [] and rows(strict) == []


def test_required_auth_accepts_a_token(strict):
    client = strict.test_client()

    assert client.post('/submit', json=PAYLOAD, headers=bearer(client)).status_code == 201
    assert len(rows(strict)) == 1


def test_preflight_needs_no_token_even_when_required(strict):
    assert strict.test_client().options('/submit').status_code == 204
