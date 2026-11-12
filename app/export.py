import hmac
import json
import sys

import click
from flask import Blueprint, current_app, jsonify, request
from flask.cli import with_appcontext

from . import auth, db

export = Blueprint('export', __name__)

# Researcher data export (ELiDDI_backend#9).
#
# One function, build_export(), makes the export. It is reached two ways:
#   - the command `flask --app app export-submissions` (run by the operator on
#     the server, through deploy/eliddi-admin), and
#   - GET /admin/export, a TEMPORARY stopgap so a researcher with no access to
#     the server can download the data. It is guarded by one shared password
#     (ELIDDI_EXPORT_PASSWORD) sent as HTTP Basic auth, so a browser asks for it
#     and then saves the file. Without that setting the route does not exist
#     (404). It is meant for one researcher in a small test: there is no
#     per-person login, no paging (the whole export is built in memory) and no
#     audit trail. The real admin system replaces it, so remove it then.


# Every Diary sent through POST /submit with a login, oldest first, each with the
# fields a researcher needs and the payload exactly as received. A Diary can be
# submitted more than once (the first goes out with status 0, a re-submission of
# the finished day with 100), so each row says whether it is `latest` for its
# Respondent, experiment and date: filter on that to get one Diary per day.
# Nothing about the Respondent leaves except their opaque id: login codes are
# never stored, and their hashes stay in the database.
def build_export(conn, experiment_id=None):
    query = (
        'SELECT id, respondent_id, experiment_id, date, status, submitted_at, payload FROM submissions'
    )
    params = ()
    if experiment_id is not None:
        query += ' WHERE experiment_id = ?'
        params = (experiment_id,)
    rows = conn.execute(query + ' ORDER BY id', params).fetchall()

    # ids only go up, so the last row seen for a day is the latest submission
    latest = {}
    for row in rows:
        latest[(row['respondent_id'], row['experiment_id'], row['date'])] = row['id']

    return {
        'exportedAt': auth.to_text(auth.utcnow()),
        'experimentID': experiment_id,
        'count': len(rows),
        'submissions': [
            {
                'id': row['id'],
                'respondentId': row['respondent_id'],
                'experimentID': row['experiment_id'],
                'date': row['date'],
                'status': row['status'],
                'submittedAt': row['submitted_at'],
                'latest': latest[(row['respondent_id'], row['experiment_id'], row['date'])] == row['id'],
                'payload': json.loads(row['payload']),
            }
            for row in rows
        ],
    }


def to_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False)


def password_challenge():
    response = jsonify(error='password required')
    response.headers['WWW-Authenticate'] = 'Basic realm="ELiDDI export", charset="UTF-8"'
    return response, 401


# The username is ignored: only the shared password counts. A request with no
# credentials is just the browser's first try before it shows its password box,
# so it is not a failure; a wrong password is, and counts towards the same
# per-address limit as wrong login codes (see auth.seconds_until_allowed).
@export.get('/admin/export')
def download_export():
    expected = current_app.config['EXPORT_PASSWORD']
    if not expected:
        return jsonify(error='not found'), 404

    conn = db.get_db()
    ip = request.remote_addr or 'unknown'

    wait = auth.seconds_until_allowed(conn, ip)
    if wait:
        response = jsonify(error='too many failed attempts, try again later')
        response.headers['Retry-After'] = str(wait)
        return response, 429

    credentials = request.authorization
    if credentials is None or credentials.type != 'basic':
        return password_challenge()
    given = (credentials.password or '').encode()
    if not hmac.compare_digest(given, expected.encode()):
        conn.execute('INSERT INTO login_failures (ip, failed_at) VALUES (?, ?)', (ip, auth.to_text(auth.utcnow())))
        return password_challenge()

    experiment_id = request.args.get('experimentID') or None
    data = build_export(conn, experiment_id)

    filename = 'eliddi-export-' + auth.utcnow().strftime('%Y%m%d') + '.json'
    response = current_app.response_class(to_json(data), mimetype='application/json')
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.headers['Cache-Control'] = 'no-store'
    return response


# flask --app app export-submissions [--experiment ID] [--output FILE]
# Prints the same JSON as the route, to the screen (so redirect it) or to a file.
@click.command('export-submissions')
@click.option('--experiment', 'experiment_id', default=None, help='Only this experimentID.')
@click.option('--output', 'output', type=click.Path(dir_okay=False, writable=True), default=None)
@with_appcontext
def export_submissions_command(experiment_id, output):
    conn = db.connect(current_app.config['DATABASE'])
    try:
        text = to_json(build_export(conn, experiment_id))
    finally:
        conn.close()

    if output:
        with open(output, 'w', encoding='utf-8') as out:
            out.write(text + '\n')
    else:
        sys.stdout.write(text + '\n')
