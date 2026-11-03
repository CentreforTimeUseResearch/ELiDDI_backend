import sqlite3

import pytest

from app import create_app, db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / 'test.sqlite3')
    yield connection
    connection.close()


def tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row['name'] for row in rows}


def write_migration(directory, name, sql):
    (directory / name).write_text(sql, encoding='utf-8')


def test_migrate_creates_the_schema_and_records_it(conn):
    applied = db.migrate(conn)

    assert applied == [1]
    assert {'respondents', 'diary_states', 'submissions', 'schema_migrations'} <= tables(conn)
    assert [row['version'] for row in conn.execute('SELECT version FROM schema_migrations')] == [1]


def test_migrate_twice_applies_nothing_the_second_time(conn):
    db.migrate(conn)

    assert db.migrate(conn) == []


def test_only_new_migrations_are_applied(conn, tmp_path):
    directory = tmp_path / 'migrations'
    directory.mkdir()
    write_migration(directory, '0001_a.sql', 'CREATE TABLE a (id INTEGER);')
    db.migrate(conn, directory)

    write_migration(directory, '0002_b.sql', 'CREATE TABLE b (id INTEGER);')

    assert db.migrate(conn, directory) == [2]
    assert {'a', 'b'} <= tables(conn)


def test_migrations_run_in_numeric_order(conn, tmp_path):
    directory = tmp_path / 'migrations'
    directory.mkdir()
    write_migration(directory, '0002_b.sql', 'INSERT INTO a VALUES (2);')
    write_migration(directory, '0001_a.sql', 'CREATE TABLE a (id INTEGER); INSERT INTO a VALUES (1);')
    write_migration(directory, '0010_c.sql', 'INSERT INTO a VALUES (10);')

    db.migrate(conn, directory)

    assert [row['id'] for row in conn.execute('SELECT id FROM a ORDER BY rowid')] == [1, 2, 10]


def test_a_failing_migration_changes_nothing_and_is_not_recorded(conn, tmp_path):
    directory = tmp_path / 'migrations'
    directory.mkdir()
    write_migration(directory, '0001_a.sql', 'CREATE TABLE a (id INTEGER);')
    write_migration(directory, '0002_bad.sql', 'CREATE TABLE b (id INTEGER); INSERT INTO missing VALUES (1);')

    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn, directory)

    assert 'a' in tables(conn)
    assert 'b' not in tables(conn)
    assert [row['version'] for row in conn.execute('SELECT version FROM schema_migrations')] == [1]


def test_duplicate_migration_numbers_are_rejected(conn, tmp_path):
    directory = tmp_path / 'migrations'
    directory.mkdir()
    write_migration(directory, '0001_a.sql', 'CREATE TABLE a (id INTEGER);')
    write_migration(directory, '0001_b.sql', 'CREATE TABLE b (id INTEGER);')

    with pytest.raises(ValueError):
        db.migrate(conn, directory)


def test_a_database_newer_than_the_code_is_refused(conn, tmp_path):
    db.migrate(conn)
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (99, '0099_future.sql')")

    with pytest.raises(RuntimeError, match='newer'):
        db.migrate(conn)


def test_foreign_keys_are_enforced(conn):
    db.migrate(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            'INSERT INTO submissions (respondent_id, experiment_id, date, status, payload) VALUES (?, ?, ?, ?, ?)',
            ('nobody', 'mumtime', '2026-10-28', 0, '{}'),
        )


def test_code_hashes_are_unique(conn):
    db.migrate(conn)
    conn.execute("INSERT INTO respondents (id, code_hash) VALUES ('a', 'h')")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO respondents (id, code_hash) VALUES ('b', 'h')")


def test_deleting_a_respondent_deletes_their_saved_state(conn):
    db.migrate(conn)
    conn.execute("INSERT INTO respondents (id, code_hash) VALUES ('a', 'h')")
    conn.execute("INSERT INTO diary_states (respondent_id, revision, state) VALUES ('a', 1, '{}')")

    conn.execute("DELETE FROM respondents WHERE id = 'a'")

    assert conn.execute('SELECT COUNT(*) FROM diary_states').fetchone()[0] == 0


def test_a_respondent_with_submissions_cannot_be_deleted(conn):
    db.migrate(conn)
    conn.execute("INSERT INTO respondents (id, code_hash) VALUES ('a', 'h')")
    conn.execute(
        'INSERT INTO submissions (respondent_id, experiment_id, date, status, payload) VALUES (?, ?, ?, ?, ?)',
        ('a', 'mumtime', '2026-10-28', 0, '{}'),
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM respondents WHERE id = 'a'")


def test_create_app_migrates_and_requests_get_a_working_connection(tmp_path):
    app = create_app(data_dir=tmp_path / 'data', database=tmp_path / 'app.sqlite3')

    with app.app_context():
        conn = db.get_db()
        assert conn is db.get_db()
        assert conn.execute('SELECT COUNT(*) FROM respondents').fetchone()[0] == 0
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1


def test_database_defaults_to_the_data_dir(tmp_path):
    create_app(data_dir=tmp_path / 'data')

    assert (tmp_path / 'data' / 'eliddi.sqlite3').exists()


def test_database_location_can_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('ELIDDI_DATABASE', str(tmp_path / 'elsewhere' / 'env.sqlite3'))

    create_app(data_dir=tmp_path / 'data')

    assert (tmp_path / 'elsewhere' / 'env.sqlite3').exists()
