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

`POST /submit` takes the JSON payload described in ELiDDI's `docs/adr/0006-diary-submission-payload.md`. It has two modes:

- **With a login token** (`Authorization: Bearer <token>`): the Diary is stored in the `submissions` table under that Respondent, exactly as received, and the answer is `201` with `{"id": …}`. `status` must be `0` or `100`. A Diary submitted again adds another row. A token that is sent but missing, unknown or expired gets `401`; it is never treated as "no token".
- **Without a token:** it is saved as `data/<experimentID>/<date>_<UTC timestamp>.json` (`data/` is gitignored) and answers `201` with the saved filename. This is for local testing without accounts, such as MUMTIME.

Set `ELIDDI_REQUIRE_AUTH=1` to refuse requests without a valid token (`401`) and so turn the file mode off. Do this on any server others can reach.

Both modes answer `400` if the body isn't a JSON object or `experimentID` / `date` are missing or unsafe to use in a path. CORS allows any origin.

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

## Login

`POST /login` with `{"code": "ABCD-EFGH"}` returns

```json
{ "token": "…", "respondentId": "c844a447-…", "expiresAt": "2026-11-04T02:46:38Z" }
```

Send the token on later requests as `Authorization: Bearer <token>`. The `respondentId` is a random, non-secret id the page uses to key its local copy of the diary; it is not a credential.

| Status | When                                                                                         |
| ------ | -------------------------------------------------------------------------------------------- |
| 200    | the code is known                                                                            |
| 400    | the body is not a JSON object with a string `code`                                           |
| 401    | the code is not known. Every kind of wrong code (bad length, unknown, empty) answers the same |
| 429    | too many failed attempts from this address. `Retry-After` says how many seconds to wait      |

`POST /logout` (needs the token) ends that one login; the Respondent's other devices stay logged in. A missing, unknown or expired token gets `401` with `WWW-Authenticate: Bearer`.

Protect a route with `@require_auth` from `app/auth.py`; the view can then read `g.respondent_id`.

**Tokens** are random (`secrets.token_urlsafe`) and only their SHA-256 is stored, so a copy of the database can't be used to act as a Respondent. They expire after `ELIDDI_TOKEN_LIFETIME` seconds (default 12 hours; households share devices, so keep it short).

**Rate limiting.** After `ELIDDI_LOGIN_MAX_FAILURES` failed attempts (default 10) within `ELIDDI_LOGIN_WINDOW` seconds (default 900), that client address gets `429`, even with a correct code, until old failures age out. Failures are kept in the database, so the limit holds across several workers. It is per address: there is deliberately no overall lockout, because anyone could trigger one to stop every Respondent logging in.

**Behind a reverse proxy**, every request comes from the proxy's address, which would put all Respondents in one bucket. Set `ELIDDI_PROXY_HOPS` to the number of proxies in front of the app so the client address is read from `X-Forwarded-For`. Leave it at 0 otherwise: the header is just whatever the client sends.

CORS allows the `Authorization` header and exposes `Retry-After` to the page.

## Respondent state

`GET /state` and `PUT /state` (both need the login token) keep a Respondent's in-progress state, so they can carry on from another device. The rules are ELiDDI's `docs/adr/0007-server-sync-model.md`. The server stores the state as one JSON snapshot per Respondent and does not read what is in it. The Respondent always comes from the token, so nobody can reach another Respondent's state.

```
GET /state   -> 200 { revision, stateVersion, state }      404 if nothing has been saved yet
PUT /state   <- { baseRevision, stateVersion, state }
             -> 200 { revision }                           accepted; the revision went up by one
             -> 409 { revision, stateVersion, state }      baseRevision was not the current revision
```

`baseRevision` is the revision the browser last saw (0 if it has seen none). A write built on anything else is refused with `409` and the current snapshot, so the browser can reconcile and try again; this is how two devices avoid overwriting each other. If nothing is stored yet, the `409` is just `{ "revision": 0 }`.

| Status | When                                                                                  |
| ------ | ------------------------------------------------------------------------------------- |
| 400    | the body is not a JSON object                                                         |
| 401    | missing, unknown or expired token                                                     |
| 413    | the body is over `ELIDDI_STATE_MAX_BYTES` (default 1,000,000)                         |
| 422    | `baseRevision` is not a whole number ≥ 0, `stateVersion` not a whole number ≥ 1, or `state` not an object |

`stateVersion` is stored with the snapshot and handed back unchanged; the browser uses it to tell whether it understands what it was given.

## Tests

```bash
docker compose run --rm backend pytest
```

## Check the environment

```bash
docker compose exec backend cat /etc/os-release
docker compose exec backend python --version
```
