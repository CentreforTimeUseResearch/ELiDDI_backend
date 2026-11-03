import json

from flask import Blueprint, current_app, g, jsonify, request

from . import auth, db

state = Blueprint('state', __name__)


def is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def snapshot(row):
    return {
        'revision': row['revision'],
        'stateVersion': row['state_version'],
        'state': json.loads(row['state']),
    }


def current(conn, respondent_id):
    return conn.execute(
        'SELECT revision, state_version, state FROM diary_states WHERE respondent_id = ?',
        (respondent_id,),
    ).fetchone()


@state.errorhandler(413)
def too_large(_error):
    return jsonify(error='state is too large'), 413


# A Respondent's in-progress state, as the browser saved it (ELiDDI
# docs/adr/0007). Each Respondent can only reach their own: the id comes from
# the login token, never from the request.
@state.route('/state', methods=['GET', 'PUT', 'OPTIONS'])
def state_endpoint():
    if request.method == 'OPTIONS':
        return '', 204

    failure = auth.authenticate()
    if failure is not None:
        return failure

    conn = db.get_db()
    if request.method == 'GET':
        row = current(conn, g.respondent_id)
        if row is None:
            return jsonify(error='no state saved yet'), 404
        response = jsonify(snapshot(row))
        response.headers['Cache-Control'] = 'no-store'
        return response

    # The server does not understand Diaries, so it checks only what it must:
    # an object of sensible size, with a version, and the revision it builds on.
    request.max_content_length = current_app.config['STATE_MAX_BYTES']
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error='body must be a JSON object'), 400
    base, version, new_state = body.get('baseRevision'), body.get('stateVersion'), body.get('state')
    if not is_integer(base) or base < 0:
        return jsonify(error='baseRevision must be a whole number, 0 or more'), 422
    if not is_integer(version) or version < 1:
        return jsonify(error='stateVersion must be a whole number, 1 or more'), 422
    if not isinstance(new_state, dict):
        return jsonify(error='state must be a JSON object'), 422

    with db.transaction(conn):
        row = current(conn, g.respondent_id)
        revision = row['revision'] if row else 0
        if base != revision:
            # stale: hand back the current snapshot so the browser can reconcile
            # (a browser claiming a revision the server has never had gets revision 0)
            return jsonify(snapshot(row) if row else {'revision': 0}), 409
        revision += 1
        conn.execute(
            'INSERT INTO diary_states (respondent_id, revision, state_version, state, updated_at)'
            ' VALUES (?, ?, ?, ?, ?)'
            ' ON CONFLICT (respondent_id) DO UPDATE SET revision = excluded.revision,'
            ' state_version = excluded.state_version, state = excluded.state,'
            ' updated_at = excluded.updated_at',
            (g.respondent_id, revision, version, json.dumps(new_state), auth.to_text(auth.utcnow())),
        )
    return jsonify(revision=revision)
