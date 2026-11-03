# ELiDDI_backend

Optional server for [ELiDDI](../ELiDDI). Target environment: Rocky Linux 10, Python 3.12 (Rocky 10's system Python), Flask, SQLite.

## Run locally

Needs Docker running.

```bash
docker compose up --build
curl http://localhost:5000/
```

Source in `app/` is bind-mounted and Flask runs in debug mode, so edits reload without a rebuild.

## Receiving a Diary

`POST /submit` takes the JSON payload described in ELiDDI's `docs/adr/0006-diary-submission-payload.md` and saves it as `data/<experimentID>/<date>_<UTC timestamp>.json` (`data/` is gitignored). It answers `201` with the saved filename, or `400` if the body isn't a JSON object or `experimentID` / `date` are missing or unsafe to use in a path. CORS allows any origin.

To use it from ELiDDI, set `general.submit_completed_diary_url` to `http://localhost:5000/submit` in the study config.

## Database

SQLite, through Python's built-in `sqlite3` module (no extra dependency). The file is `data/eliddi.sqlite3` by default (so it is gitignored and, in Docker, kept on the bind-mounted `data/` folder); set `ELIDDI_DATABASE` to put it elsewhere. Foreign keys are switched on for every connection.

Tables (see `app/migrations/0001_initial.sql` for the columns and the reasoning):

| Table               | Holds                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| `respondents`       | a random opaque id and the hash of the Respondent's login code        |
| `diary_states`      | a Respondent's in-progress state, with a revision number              |
| `submissions`       | each Diary sent through `POST /submit`, as received                   |
| `schema_migrations` | which migrations have been applied                                    |

### Migrations

Plain SQL files in `app/migrations/`, named `NNNN_description.sql` and applied in numeric order **when the app starts**. Each runs in its own transaction, so a failing one leaves the database as it was, and each is recorded in `schema_migrations` so it only runs once. Start-up refuses to run against a database that is at a newer version than the code.

To change the schema, add the next numbered file. Never edit one that has been released. Back up the SQLite file before upgrading.

Code gets a connection with `app.db.get_db()` (one per request, closed automatically). Connections are in autocommit mode: wrap writes in `with db.transaction(conn):`.

## Login codes (test phase)

A Respondent logs in with a **login code**. Lausanne has not decided how real codes are issued (probably by email), so for now the server makes dummy ones.

- **Format:** 8 characters from `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (no `0/O`, `1/I/L`), drawn with Python's `secrets` module and shown as `ABCD-EFGH`. Entry ignores case, spaces and hyphens. About 8.5 × 10^11 possible codes. Set `ELIDDI_CODE_LENGTH` and `ELIDDI_CODE_ALPHABET` to change them.
- **Stored hashed:** only an HMAC-SHA256 of the code goes in the database, keyed with `ELIDDI_CODE_HASH_KEY` (or, if that is not set, a random key created in `code_hash_key` next to the database). Keep the key: without it every stored code stops working.
- **Dummy Respondents:** with `ELIDDI_DUMMY_RESPONDENTS=6` (set in `compose.yaml`) the server makes that many Respondents at start-up and logs their codes, standing in for the email the full system will send. It is off by default and **must stay off in production**.

```bash
docker compose logs backend      # find the "TEST PHASE login codes" block
```

The codes are kept in `dummy_codes.json` next to the database, so a restart logs the same codes and makes no new Respondents. Asking for more adds only the missing ones. To start over, delete the database and `dummy_codes.json`. That file holds the codes in plain text, which is why it is for development only.

## Tests

```bash
docker compose run --rm backend pytest
```

## Check the environment

```bash
docker compose exec backend cat /etc/os-release
docker compose exec backend python --version
```
