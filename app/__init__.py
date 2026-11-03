import os
from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import codes, db, respondents
from .auth import auth as auth_blueprint
from .cors import add_cors
from .submissions import submissions


# data_dir: where file-mode submissions are saved. database: the SQLite file,
# defaulting to $ELIDDI_DATABASE, then eliddi.sqlite3 inside data_dir. The
# code hash key and dummy codes are kept in the same folder as the database.
# dummy_respondents: how many test-phase Respondents to make and log the login
# codes of at start-up, defaulting to $ELIDDI_DUMMY_RESPONDENTS, then 0 (none).
def create_app(data_dir=None, database=None, dummy_respondents=None):
    app = Flask(__name__)
    app.config['DATA_DIR'] = Path(data_dir or 'data')
    app.config['DATABASE'] = Path(
        database or os.environ.get('ELIDDI_DATABASE') or app.config['DATA_DIR'] / 'eliddi.sqlite3'
    )
    app.config['CODE_LENGTH'] = int(os.environ.get('ELIDDI_CODE_LENGTH') or codes.DEFAULT_LENGTH)
    app.config['CODE_ALPHABET'] = os.environ.get('ELIDDI_CODE_ALPHABET') or codes.DEFAULT_ALPHABET
    app.config['CODE_HASH_KEY'] = codes.load_hash_key(app.config['DATABASE'].parent, os.environ)

    app.config['TOKEN_LIFETIME'] = int(os.environ.get('ELIDDI_TOKEN_LIFETIME') or 12 * 60 * 60)  # seconds
    app.config['LOGIN_MAX_FAILURES'] = int(os.environ.get('ELIDDI_LOGIN_MAX_FAILURES') or 10)
    app.config['LOGIN_WINDOW'] = int(os.environ.get('ELIDDI_LOGIN_WINDOW') or 15 * 60)  # seconds

    # Behind a reverse proxy every request comes from the proxy's address, which
    # would put all Respondents in one rate-limit bucket. Set this to the number
    # of proxies in front of the app (and only then: the header is otherwise
    # whatever the client says).
    proxy_hops = int(os.environ.get('ELIDDI_PROXY_HOPS') or 0)
    if proxy_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops)

    db.init_app(app)

    if dummy_respondents is None:
        dummy_respondents = int(os.environ.get('ELIDDI_DUMMY_RESPONDENTS') or 0)
    if dummy_respondents:
        provide_dummy_respondents(app, dummy_respondents)

    @app.get('/')
    def index():
        return 'Hello from ELiDDI_backend\n'

    app.register_blueprint(submissions)
    app.register_blueprint(auth_blueprint)
    add_cors(app)

    return app


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
