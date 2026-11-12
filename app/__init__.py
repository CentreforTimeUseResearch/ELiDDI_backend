import os
from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import codes, db, respondents
from .auth import auth as auth_blueprint
from .cli import create_respondents_command
from .cors import add_cors, parse_origins
from .export import export as export_blueprint
from .export import export_submissions_command
from .state import state as state_blueprint
from .submissions import submissions


# A whole-number setting from the environment, or `default` when unset or empty.
# systemd's EnvironmentFile does not strip a trailing comment, so
# `ELIDDI_X=5   # note` arrives as the text "5   # note": say so, naming the
# variable, instead of leaving the operator with a bare int() error.
def env_int(name, default):
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f'{name} must be a whole number but is {value!r}. In /etc/eliddi-backend.env '
            'put comments on their own line, never after a value.'
        ) from None


# data_dir: where file-mode submissions are saved. database: the SQLite file,
# defaulting to $ELIDDI_DATABASE, then eliddi.sqlite3 inside data_dir. The
# code hash key and dummy codes are kept in the same folder as the database.
# dummy_respondents: how many test-phase Respondents to make and log the login
# codes of at start-up, defaulting to $ELIDDI_DUMMY_RESPONDENTS, then 0 (none).
# cors_origins: the origins allowed to call this backend from a page, defaulting
# to $ELIDDI_CORS_ORIGINS, then none (see cors.py).
def create_app(data_dir=None, database=None, dummy_respondents=None, cors_origins=None):
    app = Flask(__name__)
    app.config['DATA_DIR'] = Path(data_dir or 'data')
    app.config['DATABASE'] = Path(
        database or os.environ.get('ELIDDI_DATABASE') or app.config['DATA_DIR'] / 'eliddi.sqlite3'
    )
    app.config['CODE_LENGTH'] = env_int('ELIDDI_CODE_LENGTH', codes.DEFAULT_LENGTH)
    app.config['CODE_ALPHABET'] = os.environ.get('ELIDDI_CODE_ALPHABET') or codes.DEFAULT_ALPHABET
    app.config['CODE_HASH_KEY'] = codes.load_hash_key(app.config['DATABASE'].parent, os.environ)

    app.config['STATE_MAX_BYTES'] = env_int('ELIDDI_STATE_MAX_BYTES', 1_000_000)
    if cors_origins is None:
        cors_origins = os.environ.get('ELIDDI_CORS_ORIGINS')
    app.config['CORS_ORIGINS'] = parse_origins(cors_origins)
    # when set, /submit refuses a request without a valid login token
    app.config['REQUIRE_AUTH'] = os.environ.get('ELIDDI_REQUIRE_AUTH', '').lower() in ('1', 'true', 'yes')
    # the shared password for the temporary GET /admin/export (see export.py).
    # Unset or empty: the route does not exist.
    app.config['EXPORT_PASSWORD'] = os.environ.get('ELIDDI_EXPORT_PASSWORD') or None
    app.config['TOKEN_LIFETIME'] = env_int('ELIDDI_TOKEN_LIFETIME', 12 * 60 * 60)  # seconds
    app.config['LOGIN_MAX_FAILURES'] = env_int('ELIDDI_LOGIN_MAX_FAILURES', 10)
    app.config['LOGIN_WINDOW'] = env_int('ELIDDI_LOGIN_WINDOW', 15 * 60)  # seconds

    # Behind a reverse proxy every request comes from the proxy's address, which
    # would put all Respondents in one rate-limit bucket. Set this to the number
    # of proxies in front of the app (and only then: the header is otherwise
    # whatever the client says).
    proxy_hops = env_int('ELIDDI_PROXY_HOPS', 0)
    if proxy_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops)

    db.init_app(app)

    if dummy_respondents is None:
        dummy_respondents = env_int('ELIDDI_DUMMY_RESPONDENTS', 0)
    if dummy_respondents:
        provide_dummy_respondents(app, dummy_respondents)
    warn_about_unsafe_settings(app, dummy_respondents)

    @app.get('/')
    def index():
        return 'Hello from ELiDDI_backend\n'

    app.register_blueprint(submissions)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(state_blueprint)
    app.register_blueprint(export_blueprint)
    add_cors(app)
    app.cli.add_command(create_respondents_command)
    app.cli.add_command(export_submissions_command)

    return app


# What is fine on a developer's machine is not fine on a server others can
# reach. Not an error (the operator may mean it), but said in the log at
# start-up, where the person installing it will look. Silent in debug mode.
def warn_about_unsafe_settings(app, dummy_respondents):
    if app.debug:
        return
    problems = []
    if dummy_respondents:
        problems.append(
            'ELIDDI_DUMMY_RESPONDENTS is on: test login codes are written to the log and to '
            'dummy_codes.json. Turn it off (unset it) in production.'
        )
    if not app.config['REQUIRE_AUTH']:
        problems.append(
            'ELIDDI_REQUIRE_AUTH is not set: POST /submit accepts a Diary with no login and '
            'writes it to a file. Set ELIDDI_REQUIRE_AUTH=1 on a server others can reach.'
        )
    if '*' in app.config['CORS_ORIGINS']:
        problems.append(
            'ELIDDI_CORS_ORIGINS allows every origin (*). List the study page origins instead.'
        )
    export_password = app.config['EXPORT_PASSWORD']
    if export_password and len(export_password) < 16:
        problems.append(
            'ELIDDI_EXPORT_PASSWORD is shorter than 16 characters: it is the only thing between '
            'the internet and every submitted Diary. Use a long random string.'
        )
    for problem in problems:
        app.logger.warning('Unsafe for production: %s', problem)


def provide_dummy_respondents(app, count):
    conn = db.connect(app.config['DATABASE'])
    try:
        login_codes = respondents.ensure_dummy_respondents(
            conn,
            app.config['DATABASE'].parent,
            count,
            app.config['CODE_HASH_KEY'],
            app.config['CODE_LENGTH'],
            app.config['CODE_ALPHABET'],
        )
    finally:
        conn.close()

    # In debug mode the reloader runs this once to watch the files and once in
    # the process that serves, so only the serving process says anything
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return
    app.logger.warning(
        'TEST PHASE login codes (stand-in for the email sent to each Respondent):\n%s',
        '\n'.join(f'  {codes.format_code(code)}' for code in login_codes),
    )
