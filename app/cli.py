import click
from flask import current_app
from flask.cli import with_appcontext

from . import codes, db, respondents


# Makes real Respondents and prints their login codes, one per line, once. Only
# a keyed hash of each code is stored, so a code that is lost cannot be shown
# again (make a new Respondent instead).
#
# This is the interim way to issue codes until Lausanne has decided how they
# reach Respondents (probably by email): the operator runs it and passes the
# list on, then deletes the list.
#
#   flask --app app create-respondents 50 > codes.txt
@click.command('create-respondents')
@click.argument('count', type=click.IntRange(1, 100000))
@with_appcontext
def create_respondents_command(count):
    key = current_app.config['CODE_HASH_KEY']
    length = current_app.config['CODE_LENGTH']
    alphabet = current_app.config['CODE_ALPHABET']

    conn = db.connect(current_app.config['DATABASE'])
    made = []
    try:
        with db.transaction(conn):
            while len(made) < count:
                code = codes.generate_code(length, alphabet)
                taken = conn.execute(
                    'SELECT 1 FROM respondents WHERE code_hash = ?', (codes.hash_code(code, key),)
                ).fetchone()
                if code in made or taken:
                    continue  # codes must be unique
                respondents.create_respondent(conn, code, key)
                made.append(code)
    finally:
        conn.close()

    for code in made:
        click.echo(codes.format_code(code))
