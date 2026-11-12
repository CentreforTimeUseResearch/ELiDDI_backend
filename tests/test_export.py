import base64
import json

import pytest

from app import create_app, db, respondents

PASSWORD = 'a-long-shared-test-password'


def make_payload(date='2026-10-28', status=100, experiment='stratus'):
    return {
        'experimentID': experiment,
        'version': '1.0',
        'dayBoundary': '04:00',
        'date': date,
        'status': status,
        'timelines': [[{'id': 'a', 'startOffsetMins': 0, 'endOffsetMins': 1440, 'activity': 'Sleep'}]],
    }


def insert(conn, respondent_id, payload, at):
    conn.execute(
        'INSERT INTO submissions (respondent_id, experiment_id, date, status, payload, submitted_at)'
        ' VALUES (?, ?, ?, ?, ?, ?)',
        (respondent_id, payload['experimentID'], payload['date'], payload['status'], json.dumps(payload), at),
    )


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('ELIDDI_EXPORT_PASSWORD', PASSWORD)
    app = create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')
    conn = db.connect(app.config['DATABASE'])
    key = app.config['CODE_HASH_KEY']
    app.first = respondents.create_respondent(conn, 'ABCDEFGH', key)
    app.second = respondents.create_respondent(conn, 'ZZZZZZZZ', key)
    # the first Respondent sends their day twice (in progress, then complete),
    # another day once, and the second Respondent one Diary of another study
    insert(conn, app.first, make_payload(status=0), '2026-10-28T20:00:00Z')
    insert(conn, app.first, make_payload(status=100), '2026-10-28T20:05:00Z')
    insert(conn, app.first, make_payload(date='2026-10-29', status=100), '2026-10-29T20:00:00Z')
    insert(conn, app.second, make_payload(experiment='other'), '2026-10-28T21:00:00Z')
    conn.close()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def basic(password, username='researcher'):
    token = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return {'Authorization': f'Basic {token}'}


def download(client, password=PASSWORD, **query):
    return client.get('/admin/export', headers=basic(password), query_string=query)


# ---- the route is only there when a password is set

def test_without_a_password_setting_the_route_does_not_exist(tmp_path):
    app = create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')

    assert app.test_client().get('/admin/export', headers=basic('anything')).status_code == 404


def test_an_empty_password_setting_counts_as_unset(tmp_path, monkeypatch):
    monkeypatch.setenv('ELIDDI_EXPORT_PASSWORD', '')
    app = create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')

    assert app.test_client().get('/admin/export', headers=basic('')).status_code == 404


# ---- the password

def test_no_credentials_asks_the_browser_for_a_password(client):
    response = client.get('/admin/export')

    assert response.status_code == 401
    assert response.headers['WWW-Authenticate'].startswith('Basic ')


def test_a_wrong_password_is_refused_and_gives_nothing(client):
    response = download(client, 'not-the-password')

    assert response.status_code == 401
    assert response.headers['WWW-Authenticate'].startswith('Basic ')
    assert b'stratus' not in response.data


@pytest.mark.parametrize('header', ['Bearer x', 'Basic !!!not-base64', 'Basic'])
def test_other_kinds_of_credential_are_refused(client, header):
    assert client.get('/admin/export', headers={'Authorization': header}).status_code == 401


def test_any_username_works_with_the_right_password(client):
    for username in ('researcher', '', 'x'):
        response = client.get('/admin/export', headers=basic(PASSWORD, username))
        assert response.status_code == 200


def test_the_password_is_not_a_prefix_match(client):
    assert download(client, PASSWORD[:-1]).status_code == 401
    assert download(client, PASSWORD + 'x').status_code == 401


def test_a_respondent_token_does_not_open_the_export(app, client):
    token = client.post('/login', json={'code': 'ABCDEFGH'}).get_json()['token']

    response = client.get('/admin/export', headers={'Authorization': f'Bearer {token}'})

    assert response.status_code == 401


def test_too_many_wrong_passwords_are_refused_even_with_the_right_one(tmp_path, monkeypatch, app):
    monkeypatch.setenv('ELIDDI_LOGIN_MAX_FAILURES', '3')
    limited = create_app(data_dir=tmp_path / 'data', database=app.config['DATABASE'])
    client = limited.test_client()
    for _ in range(3):
        assert download(client, 'wrong').status_code == 401

    response = download(client)

    assert response.status_code == 429
    assert int(response.headers['Retry-After']) > 0


def test_asking_with_no_credentials_does_not_count_as_a_failure(tmp_path, monkeypatch, app):
    # a browser always makes this request first, before it shows its password box
    monkeypatch.setenv('ELIDDI_LOGIN_MAX_FAILURES', '2')
    limited = create_app(data_dir=tmp_path / 'data', database=app.config['DATABASE'])
    client = limited.test_client()
    for _ in range(5):
        assert client.get('/admin/export').status_code == 401

    assert download(client).status_code == 200


# ---- what is downloaded

def test_it_downloads_as_a_json_file_that_is_not_cached(client):
    response = download(client)

    assert response.status_code == 200
    assert response.mimetype == 'application/json'
    assert response.headers['Content-Disposition'].startswith('attachment; filename="eliddi-export-')
    assert response.headers['Content-Disposition'].endswith('.json"')
    assert response.headers['Cache-Control'] == 'no-store'


def test_it_holds_every_submission_with_its_payload_as_received(app, client):
    data = download(client).get_json()

    assert data['count'] == 4
    assert [s['payload'] for s in data['submissions']] == [
        make_payload(status=0),
        make_payload(status=100),
        make_payload(date='2026-10-29', status=100),
        make_payload(experiment='other'),
    ]
    first = data['submissions'][0]
    assert first['respondentId'] == app.first
    assert (first['experimentID'], first['date'], first['status']) == ('stratus', '2026-10-28', 0)
    assert first['submittedAt'] == '2026-10-28T20:00:00Z'
    assert data['exportedAt']


def test_latest_marks_the_last_submission_of_each_respondent_experiment_and_day(client):
    submissions = download(client).get_json()['submissions']

    assert [s['latest'] for s in submissions] == [False, True, True, True]


def test_latest_keeps_respondents_and_experiments_apart(app, tmp_path):
    conn = db.connect(app.config['DATABASE'])
    # the second Respondent sends the same study and day as the first
    insert(conn, app.second, make_payload(status=100), '2026-10-28T22:00:00Z')
    conn.close()

    submissions = download(app.test_client()).get_json()['submissions']

    mine = [s for s in submissions if s['respondentId'] == app.first and s['date'] == '2026-10-28']
    theirs = [s for s in submissions if s['respondentId'] == app.second and s['experimentID'] == 'stratus']
    assert [s['latest'] for s in mine] == [False, True]
    assert [s['latest'] for s in theirs] == [True]


def test_it_can_be_limited_to_one_experiment(client):
    data = download(client, experimentID='other').get_json()

    assert data['experimentID'] == 'other'
    assert data['count'] == 1
    assert [s['experimentID'] for s in data['submissions']] == ['other']


def test_an_experiment_with_nothing_exports_an_empty_list(client):
    data = download(client, experimentID='nope').get_json()

    assert data['count'] == 0 and data['submissions'] == []


def test_nothing_that_could_be_used_to_log_in_is_in_it(client):
    text = download(client).get_data(as_text=True)

    assert 'ABCDEFGH' not in text and 'code_hash' not in text and 'token' not in text.lower()


def test_an_empty_database_exports_an_empty_list(tmp_path, monkeypatch):
    monkeypatch.setenv('ELIDDI_EXPORT_PASSWORD', PASSWORD)
    app = create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')

    data = download(app.test_client()).get_json()

    assert data['count'] == 0 and data['submissions'] == []


def test_non_ascii_text_is_kept_as_written(app, client):
    conn = db.connect(app.config['DATABASE'])
    payload = make_payload(date='2026-10-30')
    payload['timelines'][0][0]['activity'] = 'Schlafen / Dormir / Café'
    insert(conn, app.first, payload, '2026-10-30T20:00:00Z')
    conn.close()

    response = download(client)

    assert 'Schlafen / Dormir / Café' in response.get_data(as_text=True)


# ---- the command

def run(app, *args):
    return app.test_cli_runner().invoke(args=['export-submissions', *args])


def test_the_command_prints_the_same_export(app, client):
    result = run(app)

    assert result.exit_code == 0
    printed = json.loads(result.output)
    served = download(client).get_json()
    assert printed['submissions'] == served['submissions']
    assert printed['count'] == 4


def test_the_command_can_be_limited_to_one_experiment(app):
    printed = json.loads(run(app, '--experiment', 'other').output)

    assert printed['count'] == 1 and printed['experimentID'] == 'other'


def test_the_command_can_write_a_file(app, tmp_path):
    target = tmp_path / 'out.json'

    result = run(app, '--output', str(target))

    assert result.exit_code == 0 and result.output == ''
    assert json.loads(target.read_text(encoding='utf-8'))['count'] == 4


def test_the_command_needs_no_password(tmp_path):
    # run by the operator on the server, so shell access is the authorisation
    app = create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')

    result = run(app)

    assert result.exit_code == 0 and json.loads(result.output)['count'] == 0


# ---- start-up warning

def test_a_short_password_is_warned_about(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('ELIDDI_EXPORT_PASSWORD', 'short')

    create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')

    assert 'ELIDDI_EXPORT_PASSWORD is shorter than 16 characters' in caplog.text


def test_a_long_password_is_not_warned_about(tmp_path, caplog):
    create_app(data_dir=tmp_path / 'data', database=tmp_path / 'eliddi.sqlite3')

    assert 'ELIDDI_EXPORT_PASSWORD' not in caplog.text
