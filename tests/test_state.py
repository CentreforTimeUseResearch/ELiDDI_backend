import pytest

from app import auth, create_app, db, respondents

CODE = 'ABCDEFGH'
OTHER_CODE = 'ZZZZZZZZ'
STATE = {
    'onboarding': True,
    'diaries': {
        '2026-10-28': {
            'status': 0,
            'timelines': [[{'id': 'a', 'startOffsetMins': 0, 'endOffsetMins': 60, 'activity': 'Sleep'}], None],
        }
    },
}


@pytest.fixture
def app(tmp_path):
    app = create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')
    conn = db.connect(app.config['DATABASE'])
    app.respondent_id = respondents.create_respondent(conn, CODE, app.config['CODE_HASH_KEY'])
    app.other_id = respondents.create_respondent(conn, OTHER_CODE, app.config['CODE_HASH_KEY'])
    conn.close()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def bearer(client, code=CODE):
    token = client.post('/login', json={'code': code}).get_json()['token']
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def headers(client):
    return bearer(client)


def put(client, headers, base=0, state=STATE, version=1, **extra):
    return client.put('/state', json={'baseRevision': base, 'stateVersion': version, 'state': state, **extra}, headers=headers)


# ---- reading

def test_a_new_respondent_has_no_state(client, headers):
    assert client.get('/state', headers=headers).status_code == 404


def test_round_trip(client, headers):
    response = put(client, headers)

    assert response.status_code == 200
    assert response.get_json() == {'revision': 1}

    got = client.get('/state', headers=headers)
    assert got.status_code == 200
    assert got.get_json() == {'revision': 1, 'stateVersion': 1, 'state': STATE}
    assert got.headers['Cache-Control'] == 'no-store'


def test_state_comes_back_unchanged_whatever_is_in_it(client, headers):
    odd = {'diaries': {}, 'extra': [1, 'é', None, {'deep': [True]}], 'unknownSlice': 3.5}

    put(client, headers, state=odd)

    assert client.get('/state', headers=headers).get_json()['state'] == odd


# ---- revisions

def test_each_accepted_write_raises_the_revision_by_one(client, headers):
    assert put(client, headers, base=0).get_json() == {'revision': 1}
    assert put(client, headers, base=1).get_json() == {'revision': 2}
    assert put(client, headers, base=2).get_json() == {'revision': 3}


def test_a_stale_write_is_refused_with_the_current_snapshot(client, headers):
    put(client, headers, base=0, state={'diaries': {}})
    put(client, headers, base=1, state=STATE)

    response = put(client, headers, base=1, state={'diaries': {'stale': {'timelines': []}}})

    assert response.status_code == 409
    assert response.get_json() == {'revision': 2, 'stateVersion': 1, 'state': STATE}
    assert client.get('/state', headers=headers).get_json()['state'] == STATE


def test_a_first_write_that_claims_a_revision_is_refused(client, headers):
    response = put(client, headers, base=5)

    assert response.status_code == 409
    assert response.get_json() == {'revision': 0}
    assert client.get('/state', headers=headers).status_code == 404


def test_writing_ahead_of_the_server_is_refused(client, headers):
    put(client, headers, base=0)

    assert put(client, headers, base=2).status_code == 409


def test_two_devices_cannot_both_win(client, app):
    laptop, tablet = bearer(client), bearer(client)
    put(client, laptop, base=0)

    assert put(client, laptop, base=1).status_code == 200
    assert put(client, tablet, base=1).status_code == 409


def test_state_version_is_stored_with_the_snapshot(client, headers):
    put(client, headers, version=3)

    assert client.get('/state', headers=headers).get_json()['stateVersion'] == 3


# ---- Respondents are separate

def test_another_respondent_never_sees_my_state(client, headers):
    put(client, headers)
    other = bearer(client, OTHER_CODE)

    assert client.get('/state', headers=other).status_code == 404


def test_another_respondent_has_their_own_revision(client, headers):
    put(client, headers, base=0)
    put(client, headers, base=1)
    other = bearer(client, OTHER_CODE)

    assert put(client, other, base=0, state={'diaries': {}}).get_json() == {'revision': 1}
    assert client.get('/state', headers=headers).get_json()['state'] == STATE


def test_the_respondent_comes_from_the_token_not_the_request(client, app, headers):
    put(client, headers, respondentId=app.other_id, respondent_id=app.other_id)

    other = bearer(client, OTHER_CODE)
    assert client.get('/state', headers=other).status_code == 404


def test_logging_in_again_still_reaches_the_same_state(client, headers):
    put(client, headers)

    assert client.get('/state', headers=bearer(client)).get_json()['state'] == STATE


# ---- authentication

@pytest.mark.parametrize('method', ['get', 'put'])
def test_a_token_is_required(client, method):
    response = getattr(client, method)('/state', json={'baseRevision': 0, 'stateVersion': 1, 'state': {}})

    assert response.status_code == 401
    assert response.headers['WWW-Authenticate'] == 'Bearer'


def test_a_refused_write_changes_nothing(client, app):
    client.put('/state', json={'baseRevision': 0, 'stateVersion': 1, 'state': STATE})

    conn = db.connect(app.config['DATABASE'])
    assert conn.execute('SELECT COUNT(*) FROM diary_states').fetchone()[0] == 0
    conn.close()


def test_the_state_goes_when_the_respondent_does(client, app, headers):
    put(client, headers)

    conn = db.connect(app.config['DATABASE'])
    conn.execute('DELETE FROM respondents WHERE id = ?', (app.respondent_id,))
    assert conn.execute('SELECT COUNT(*) FROM diary_states').fetchone()[0] == 0
    conn.close()


# ---- validation

@pytest.mark.parametrize('body', [[], 'x', 5, None])
def test_the_body_must_be_a_json_object(client, headers, body):
    assert client.put('/state', json=body, headers=headers).status_code == 400


def test_a_body_that_is_not_json_is_a_400(client, headers):
    assert client.put('/state', data='nope', content_type='text/plain', headers=headers).status_code == 400


@pytest.mark.parametrize('state', [[], 'x', 5, None, True])
def test_state_must_be_an_object(client, headers, state):
    assert put(client, headers, state=state).status_code == 422


@pytest.mark.parametrize('base', [-1, 1.5, '0', None, True])
def test_base_revision_must_be_a_whole_number(client, headers, base):
    assert put(client, headers, base=base).status_code == 422


@pytest.mark.parametrize('version', [0, -1, 1.5, '1', None, True])
def test_state_version_must_be_a_positive_whole_number(client, headers, version):
    assert put(client, headers, version=version).status_code == 422


@pytest.mark.parametrize('field', ['baseRevision', 'stateVersion', 'state'])
def test_every_field_is_required(client, headers, field):
    body = {'baseRevision': 0, 'stateVersion': 1, 'state': {}}
    del body[field]

    assert client.put('/state', json=body, headers=headers).status_code == 422


def test_an_invalid_write_stores_nothing(client, headers):
    put(client, headers, state=[])

    assert client.get('/state', headers=headers).status_code == 404


def test_an_empty_object_is_a_valid_state(client, headers):
    assert put(client, headers, state={}).status_code == 200


def test_too_large_a_state_is_refused(client, headers, app):
    app.config['STATE_MAX_BYTES'] = 200

    response = put(client, headers, state={'diaries': {'x': 'y' * 500}})

    assert response.status_code == 413
    assert response.get_json() == {'error': 'state is too large'}
    assert client.get('/state', headers=headers).status_code == 404


def test_a_moderate_state_is_accepted_under_the_default_limit(client, headers):
    assert put(client, headers, state={'diaries': {'x': 'y' * 500}}).status_code == 200


def test_the_size_limit_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('ELIDDI_STATE_MAX_BYTES', '123')

    assert create_app(data_dir=tmp_path / 'd', database=tmp_path / 'x.sqlite3').config['STATE_MAX_BYTES'] == 123


# ---- CORS

def test_preflight_needs_no_token_and_allows_get_and_put(client):
    response = client.options('/state')

    assert response.status_code == 204
    allowed = response.headers['Access-Control-Allow-Methods']
    assert 'GET' in allowed and 'PUT' in allowed
    assert 'Authorization' in response.headers['Access-Control-Allow-Headers']


def test_responses_carry_the_cors_header(client, headers):
    assert put(client, headers).headers['Access-Control-Allow-Origin'] == '*'
    assert client.get('/state', headers=headers).headers['Access-Control-Allow-Origin'] == '*'
    assert client.get('/state').headers['Access-Control-Allow-Origin'] == '*'
