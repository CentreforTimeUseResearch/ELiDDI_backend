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

## Tests

```bash
docker compose run --rm backend pytest
```

## Check the environment

```bash
docker compose exec backend cat /etc/os-release
docker compose exec backend python --version
```
