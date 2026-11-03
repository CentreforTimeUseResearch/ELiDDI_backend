import os
from pathlib import Path

from flask import Flask

from . import db
from .cors import add_cors
from .submissions import submissions


# data_dir: where file-mode submissions are saved. database: the SQLite file,
# defaulting to $ELIDDI_DATABASE, then eliddi.sqlite3 inside data_dir.
def create_app(data_dir=None, database=None):
    app = Flask(__name__)
    app.config['DATA_DIR'] = Path(data_dir or 'data')
    app.config['DATABASE'] = Path(
        database or os.environ.get('ELIDDI_DATABASE') or app.config['DATA_DIR'] / 'eliddi.sqlite3'
    )

    db.init_app(app)

    @app.get('/')
    def index():
        return 'Hello from ELiDDI_backend\n'

    app.register_blueprint(submissions)
    add_cors(app)

    return app
