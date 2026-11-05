import json
import logging

import pytest

from app import codes, create_app, db


@pytest.fixture
def paths(tmp_path):
    return {'data_dir': tmp_path / 'data', 'database': tmp_path / 'state' / 'eliddi.sqlite3'}


def rows(app):
    conn = db.connect(app.config['DATABASE'])
    try:
        return conn.execute('SELECT * FROM respondents').fetchall()
    finally:
        conn.close()


def stored_codes(app):
    return json.loads((app.config['DATABASE'].parent / 'dummy_codes.json').read_text(encoding='utf-8'))


def test_no_dummy_respondents_by_default(paths):
    app = create_app(**paths)

    assert rows(app) == []
    assert not (app.config['DATABASE'].parent / 'dummy_codes.json').exists()


def test_environment_variable_turns_them_on(paths, monkeypatch):
    monkeypatch.setenv('ELIDDI_DUMMY_RESPONDENTS', '3')

    assert len(rows(create_app(**paths))) == 3


def test_creates_the_requested_number_with_unique_codes(paths):
    app = create_app(**paths, dummy_respondents=6)

    login_codes = stored_codes(app)
    assert len(rows(app)) == 6
    assert len(set(login_codes)) == 6
    assert all(len(code) == 8 and set(code) <= set(codes.DEFAULT_ALPHABET) for code in login_codes)


def test_respondent_ids_are_random_not_counters(paths):
    ids = [row['id'] for row in rows(create_app(**paths, dummy_respondents=6))]

    assert len(set(ids)) == 6
    assert not any(i.isdigit() for i in ids)


def test_codes_are_stored_hashed_and_findable(paths):
    app = create_app(**paths, dummy_respondents=2)
    key = app.config['CODE_HASH_KEY']

    stored_hashes = {row['code_hash'] for row in rows(app)}
    for code in stored_codes(app):
        assert code not in stored_hashes
        assert codes.hash_code(code, key) in stored_hashes
        assert codes.hash_code(codes.format_code(code).lower(), key) in stored_hashes


def test_the_database_file_does_not_contain_the_plain_codes(paths):
    app = create_app(**paths, dummy_respondents=3)

    raw = app.config['DATABASE'].read_bytes()
    for code in stored_codes(app):
        assert code.encode() not in raw


def test_a_restart_keeps_the_same_codes_and_adds_no_respondents(paths):
    first = stored_codes(create_app(**paths, dummy_respondents=6))

    app = create_app(**paths, dummy_respondents=6)

    assert stored_codes(app) == first
    assert len(rows(app)) == 6


def test_asking_for_more_adds_only_the_missing_ones(paths):
    first = stored_codes(create_app(**paths, dummy_respondents=2))

    app = create_app(**paths, dummy_respondents=4)

    assert stored_codes(app)[:2] == first
    assert len(rows(app)) == 4


def test_codes_are_logged_once_in_groups_of_four(paths, caplog):
    with caplog.at_level(logging.WARNING):
        app = create_app(**paths, dummy_respondents=3)

    # (the start-up check adds its own, separate warnings about unsafe settings)
    assert len([r for r in caplog.records if 'TEST PHASE' in r.getMessage()]) == 1
    for code in stored_codes(app):
        assert codes.format_code(code) in caplog.text


def test_codes_are_not_logged_by_the_debug_reloader_process(paths, caplog, monkeypatch):
    monkeypatch.setenv('FLASK_DEBUG', '1')
    monkeypatch.delenv('WERKZEUG_RUN_MAIN', raising=False)

    with caplog.at_level(logging.WARNING):
        app = create_app(**paths, dummy_respondents=3)

    assert caplog.records == []
    assert len(rows(app)) == 3


def test_codes_are_logged_by_the_debug_serving_process(paths, caplog, monkeypatch):
    monkeypatch.setenv('FLASK_DEBUG', '1')
    monkeypatch.setenv('WERKZEUG_RUN_MAIN', 'true')

    with caplog.at_level(logging.WARNING):
        create_app(**paths, dummy_respondents=3)

    assert len(caplog.records) == 1


def test_code_length_and_alphabet_come_from_the_environment(paths, monkeypatch):
    monkeypatch.setenv('ELIDDI_CODE_LENGTH', '10')
    monkeypatch.setenv('ELIDDI_CODE_ALPHABET', 'XY')

    app = create_app(**paths, dummy_respondents=2)

    assert all(len(code) == 10 and set(code) <= {'X', 'Y'} for code in stored_codes(app))


def test_submission_folder_is_left_alone(paths):
    create_app(**paths, dummy_respondents=3)

    assert not paths['data_dir'].exists()
