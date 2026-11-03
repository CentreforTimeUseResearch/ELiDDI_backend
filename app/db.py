import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

MIGRATIONS_DIR = Path(__file__).parent / 'migrations'


def connect(path):
    # autocommit: transactions are explicit, through transaction() below
    conn = sqlite3.connect(path, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    # SQLite ignores foreign keys unless asked, per connection
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def transaction(conn):
    # IMMEDIATE takes the write lock up front, so two writers (or two workers
    # migrating at once) queue instead of failing half way through
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
    except BaseException:
        conn.execute('ROLLBACK')
        raise
    conn.execute('COMMIT')


def split_statements(sql):
    # sqlite3 runs one statement per execute(), and executescript() would
    # commit our transaction first. Cut after each ';' and let SQLite say
    # whether that ';' really ended a statement (not one in a string or trigger)
    statement = ''
    for piece in re.split(r'(?<=;)', sql):
        statement += piece
        if sqlite3.complete_statement(statement):
            yield statement
            statement = ''
    if statement.strip():
        raise ValueError(f'incomplete SQL statement: {statement.strip()[:60]!r}')


def migration_files(migrations_dir):
    # 0001_name.sql, 0002_name.sql ... applied in numeric order
    files = {}
    for path in Path(migrations_dir).glob('*.sql'):
        version = int(path.name.split('_', 1)[0])
        if version in files:
            raise ValueError(f'two migrations numbered {version}')
        files[version] = path
    return dict(sorted(files.items()))


# Applies every migration not yet recorded in schema_migrations, each in its
# own transaction (a failed one leaves the database as it was before it).
# Returns the versions applied.
def migrate(conn, migrations_dir=MIGRATIONS_DIR):
    conn.execute(
        'CREATE TABLE IF NOT EXISTS schema_migrations ('
        ' version INTEGER PRIMARY KEY,'
        ' name TEXT NOT NULL,'
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))"
    )
    files = migration_files(migrations_dir)

    applied = []
    for version, path in files.items():
        with transaction(conn):
            # checked inside the lock, in case another process just applied it
            if conn.execute('SELECT 1 FROM schema_migrations WHERE version = ?', (version,)).fetchone():
                continue
            for statement in split_statements(path.read_text(encoding='utf-8')):
                conn.execute(statement)
            conn.execute('INSERT INTO schema_migrations (version, name) VALUES (?, ?)', (version, path.name))
        applied.append(version)

    # a database from a newer release than this code must not be used by it
    newest = conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    if newest is not None and newest > max(files, default=0):
        raise RuntimeError(f'database is at schema version {newest}, newer than this code knows ({max(files, default=0)})')
    return applied


def get_db():
    if 'db' not in g:
        g.db = connect(current_app.config['DATABASE'])
    return g.db


def close_db(error=None):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()


def init_app(app):
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(app.config['DATABASE'])
    try:
        migrate(conn)
    finally:
        conn.close()
    app.teardown_appcontext(close_db)
