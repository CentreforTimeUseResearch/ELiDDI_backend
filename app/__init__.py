from pathlib import Path

from flask import Flask

from .cors import add_cors
from .submissions import submissions


def create_app(data_dir=None):
    app = Flask(__name__)
    app.config['DATA_DIR'] = Path(data_dir or 'data')

    @app.get('/')
    def index():
        return 'Hello from ELiDDI_backend\n'

    app.register_blueprint(submissions)
    add_cors(app)

    return app
