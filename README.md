# ELiDDI_backend

Optional server for [ELiDDI](../ELiDDI). Target environment: Rocky Linux 10, Python 3.15.1, Flask, SQLite.

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

## Tests

```bash
docker compose run --rm backend pytest
```

## Check the environment

```bash
docker compose exec backend cat /etc/os-release
docker compose exec backend python --version
```
