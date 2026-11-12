import logging

import pytest

from app import create_app, db


@pytest.fixture
def paths(tmp_path):
    return {'data_dir': tmp_path / 'data', 'database': tmp_path / 'eliddi.sqlite3'}


def preflight(app, origin):
    return app.test_client().options('/state', headers={'Origin': origin})


# ---- CORS

def test_a_listed_origin_is_echoed_back_with_vary(paths):
    app = create_app(**paths, cors_origins='https://stratus.example.org,https://other.example.org')

    response = preflight(app, 'https://other.example.org')

    assert response.headers['Access-Control-Allow-Origin'] == 'https://other.example.org'
    assert 'Origin' in response.headers['Vary']
    assert 'Authorization' in response.headers['Access-Control-Allow-Headers']
    assert 'PUT' in response.headers['Access-Control-Allow-Methods']
    assert 'Retry-After' in response.headers['Access-Control-Expose-Headers']


def test_an_unlisted_origin_gets_no_cors_headers(paths):
    app = create_app(**paths, cors_origins='https://stratus.example.org')

    response = preflight(app, 'https://evil.example.org')

    assert 'Access-Control-Allow-Origin' not in response.headers
    assert 'Access-Control-Allow-Headers' not in response.headers


def test_a_request_with_no_origin_gets_no_cors_headers(paths):
    app = create_app(**paths, cors_origins='https://stratus.example.org')

    assert 'Access-Control-Allow-Origin' not in app.test_client().get('/').headers


def test_a_trailing_slash_and_spaces_in_the_setting_do_not_matter(paths):
    app = create_app(**paths, cors_origins=' https://stratus.example.org/ , https://b.example.org ')

    assert preflight(app, 'https://stratus.example.org').headers['Access-Control-Allow-Origin'] == (
        'https://stratus.example.org'
    )


def test_an_origin_that_only_starts_like_a_listed_one_is_refused(paths):
    app = create_app(**paths, cors_origins='https://stratus.example.org')

    response = preflight(app, 'https://stratus.example.org.evil.example')

    assert 'Access-Control-Allow-Origin' not in response.headers


def test_a_star_allows_every_origin(paths):
    app = create_app(**paths, cors_origins='*')

    assert preflight(app, 'https://anything.example').headers['Access-Control-Allow-Origin'] == '*'


def test_unset_means_no_cross_origin_access(paths, monkeypatch):
    monkeypatch.delenv('ELIDDI_CORS_ORIGINS')
    app = create_app(**paths)

    assert app.config['CORS_ORIGINS'] == []
    assert 'Access-Control-Allow-Origin' not in preflight(app, 'https://stratus.example.org').headers


def test_the_environment_variable_sets_the_origins(paths, monkeypatch):
    monkeypatch.setenv('ELIDDI_CORS_ORIGINS', 'https://stratus.example.org')

    assert create_app(**paths).config['CORS_ORIGINS'] == ['https://stratus.example.org']


# ---- the start-up check

def warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_a_safe_production_setup_says_nothing(paths, monkeypatch, caplog):
    monkeypatch.setenv('ELIDDI_REQUIRE_AUTH', '1')

    with caplog.at_level(logging.WARNING):
        create_app(**paths, cors_origins='https://stratus.example.org')

    assert warnings(caplog) == []


def test_each_unsafe_setting_is_named(paths, caplog):
    with caplog.at_level(logging.WARNING):
        create_app(**paths, dummy_respondents=2, cors_origins='*')

    text = '\n'.join(warnings(caplog))
    assert 'ELIDDI_DUMMY_RESPONDENTS' in text
    assert 'ELIDDI_REQUIRE_AUTH' in text
    assert 'ELIDDI_CORS_ORIGINS' in text


# ---- creating real Respondents

def test_create_respondents_prints_working_codes_and_stores_only_hashes(paths):
    app = create_app(**paths, cors_origins='*')

    result = app.test_cli_runner().invoke(args=['create-respondents', '3'])

    assert result.exit_code == 0
    printed = result.output.split()
    assert len(printed) == 3 and len(set(printed)) == 3

    conn = db.connect(app.config['DATABASE'])
    try:
        stored = [row['code_hash'] for row in conn.execute('SELECT code_hash FROM respondents')]
    finally:
        conn.close()
    assert len(stored) == 3
    assert all(printed_code not in ''.join(stored) for printed_code in printed)

    client = app.test_client()
    for code in printed:
        assert client.post('/login', json={'code': code}).status_code == 200


def test_create_respondents_adds_to_the_ones_already_there(paths):
    app = create_app(**paths, cors_origins='*')
    runner = app.test_cli_runner()

    first = runner.invoke(args=['create-respondents', '2']).output.split()
    second = runner.invoke(args=['create-respondents', '2']).output.split()

    assert not set(first) & set(second)
    conn = db.connect(app.config['DATABASE'])
    try:
        assert conn.execute('SELECT COUNT(*) FROM respondents').fetchone()[0] == 4
    finally:
        conn.close()


def test_create_respondents_refuses_a_count_that_is_not_positive(paths):
    app = create_app(**paths, cors_origins='*')

    assert app.test_cli_runner().invoke(args=['create-respondents', '0']).exit_code != 0


# ---- numbers in the environment

@pytest.mark.parametrize('name', [
    'ELIDDI_DUMMY_RESPONDENTS', 'ELIDDI_TOKEN_LIFETIME', 'ELIDDI_LOGIN_MAX_FAILURES',
    'ELIDDI_LOGIN_WINDOW', 'ELIDDI_STATE_MAX_BYTES', 'ELIDDI_CODE_LENGTH', 'ELIDDI_PROXY_HOPS',
])
def test_a_number_with_a_trailing_comment_names_the_setting_and_the_cause(paths, monkeypatch, name):
    # systemd's EnvironmentFile keeps the comment as part of the value
    monkeypatch.setenv(name, '5   #test-phase note')

    with pytest.raises(ValueError) as error:
        create_app(**paths)

    message = str(error.value)
    assert name in message and '5   #test-phase note' in message
    assert 'comments on their own line' in message


def test_an_empty_number_uses_the_default(paths, monkeypatch):
    monkeypatch.setenv('ELIDDI_LOGIN_WINDOW', '')

    assert create_app(**paths).config['LOGIN_WINDOW'] == 15 * 60


def test_a_plain_number_is_read(paths, monkeypatch):
    monkeypatch.setenv('ELIDDI_LOGIN_WINDOW', '120')

    assert create_app(**paths).config['LOGIN_WINDOW'] == 120
