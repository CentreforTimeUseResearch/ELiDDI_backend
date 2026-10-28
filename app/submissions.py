import json
import os
import re
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

submissions = Blueprint('submissions', __name__)

# Both values become part of a path, so only accept what is safe there
EXPERIMENT_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


def is_valid_date(value):
    if not isinstance(value, str) or not DATE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return False
    return True


# Receives one Diary (payload described in ELiDDI docs/adr/0006) and saves it
# as data/<experimentID>/<date>_<UTC timestamp>.json
@submissions.route('/submit', methods=['POST', 'OPTIONS'])
def submit():
    if request.method == 'OPTIONS':
        return '', 204

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='body must be a JSON object'), 400

    experiment_id = payload.get('experimentID')
    date = payload.get('date')
    if not isinstance(experiment_id, str) or not EXPERIMENT_ID.fullmatch(experiment_id):
        return jsonify(error='experimentID is missing or invalid'), 400
    if not is_valid_date(date):
        return jsonify(error='date is missing or not YYYY-MM-DD'), 400

    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = current_app.config['DATA_DIR'] / experiment_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{date}_{timestamp}.json'

    # write then rename, so a partly written file is never left under the final name
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    os.replace(temp, path)

    return jsonify(saved=path.name), 201
