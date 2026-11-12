# Installing and running the backend in production

For the people who will run the ELiDDI backend on a Rocky Linux 10 server (University of Lausanne computing centre, for STRATUS). It assumes you are comfortable with Linux administration, `systemd` and `nginx`, and have never seen this project. Everything here is written so you do not need us to keep it running.

If you only want to try it on a laptop, use the Docker set-up in the [README](../README.md) instead. **That set-up is for testing and must not be used for a real study** (see [the checklist](#production-checklist)).

## What you are installing

```
Respondent's browser  ──https──►  nginx (443)  ──http, this machine only──►  gunicorn (127.0.0.1:8000)  ──►  Flask app  ──►  SQLite file
  (the ELiDDI page, served                 │                                                                       /var/lib/eliddi/eliddi.sqlite3
   from a different site)                  └─ TLS certificate, HTTP→HTTPS redirect
```

- **The page** (the diary itself) is a static website served from somewhere else, for example the study's GitHub Pages site. It is not part of this install.
- **The backend** (this repository) provides login by code, saving a Respondent's diary so they can carry on from another device, and receiving the finished diary. It stores everything in one SQLite file.
- **Python 3.12**, which is Rocky 10's own `python3`. No other Python is needed.

## Before you start

You need:

- A Rocky Linux 10 server with root (or `sudo`), reachable from the Internet on ports 80 and 443.
- A host name for it (the guide uses `diary.example.org`) and a TLS certificate and key for that name. Use whatever your centre normally issues. The guide only says where the files go.
- The **origin of each study page** that will call the backend: scheme and host, no path, for example `https://stratus.github.io`. The backend refuses calls from pages it has not been told about.

## 1. Install the packages

```bash
sudo dnf install -y python3 python3-pip nginx git
```

## 2. Create the service user and folders

```bash
sudo useradd --system --home-dir /var/lib/eliddi --shell /sbin/nologin eliddi
sudo install -d -o eliddi -g eliddi -m 750 /var/lib/eliddi       # the database lives here
sudo install -d -o eliddi -g eliddi -m 700 /var/backups/eliddi   # nightly backups
```

## 3. Get the code and install its dependencies

```bash
sudo git clone https://github.com/CentreforTimeUseResearch/ELiDDI_backend.git /opt/eliddi-backend
cd /opt/eliddi-backend
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt
sudo chmod +x deploy/eliddi-admin deploy/backup.sh
```

`requirements.txt` holds only what the server needs to run (Flask and gunicorn). The test tools are in `requirements-dev.txt` and are not installed here. If the server cannot reach GitHub, copy the folder over instead of cloning it; nothing else changes.

## 4. Write the settings file

```bash
sudo cp deploy/eliddi-backend.env.example /etc/eliddi-backend.env
sudo chown root:eliddi /etc/eliddi-backend.env
sudo chmod 640 /etc/eliddi-backend.env
python3 -c "import secrets; print(secrets.token_hex(32))"     # make a code hash key
sudo nano /etc/eliddi-backend.env
```

Edit the file: paste the key as `ELIDDI_CODE_HASH_KEY`, and set `ELIDDI_CORS_ORIGINS` to the study page origin(s), separated by commas. Leave the rest as it is for now. **Keep a copy of the code hash key somewhere safe**: login codes are stored only as a hash made with it, so without it every code stops working.

### All the settings

| Setting                       | Default                       | Meaning                                                                                                                                              |
| ----------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ELIDDI_DATABASE`             | `data/eliddi.sqlite3`         | The SQLite file. Use `/var/lib/eliddi/eliddi.sqlite3`.                                                                                                |
| `ELIDDI_REQUIRE_AUTH`         | off                           | **Set to `1`.** Without it `POST /submit` accepts a Diary with no login and writes it to a file.                                                       |
| `ELIDDI_CORS_ORIGINS`         | none (no page may call it)    | **Set it.** Comma-separated origins of the study pages. `*` allows every page: for testing only.                                                       |
| `ELIDDI_PROXY_HOPS`           | `0`                           | **Set to `1`** behind nginx, so the login rate limit sees each Respondent's own address. Leave `0` when nothing is in front (the header is then forgeable). |
| `ELIDDI_CODE_HASH_KEY`        | a random key kept in `code_hash_key` next to the database | The key login codes are hashed with. Set it explicitly so it is in your records, and back it up.                                  |
| `ELIDDI_EXPORT_PASSWORD`      | unset (no route)              | Turns on the **temporary** researcher download at `/admin/export`. See [Giving a researcher the data](#giving-a-researcher-the-data). Use at least 16 random characters.                |
| `ELIDDI_DUMMY_RESPONDENTS`    | `0`                           | Test-phase login codes, written to the log and to `dummy_codes.json`. **Must not be set in production.**                                              |
| `ELIDDI_TOKEN_LIFETIME`       | `43200` (12 hours)            | How long a login lasts, in seconds. Households share devices, so keep it short.                                                                       |
| `ELIDDI_LOGIN_MAX_FAILURES`   | `10`                          | Wrong codes allowed from one address within `ELIDDI_LOGIN_WINDOW`, after which it gets `429` until they age out.                                       |
| `ELIDDI_LOGIN_WINDOW`         | `900` (15 minutes)            | See above, in seconds.                                                                                                                                |
| `ELIDDI_STATE_MAX_BYTES`      | `1000000`                     | The largest saved diary the server accepts. Keep `client_max_body_size` in nginx above it.                                                            |
| `ELIDDI_CODE_LENGTH`, `ELIDDI_CODE_ALPHABET` | 8 characters, no look-alikes | The shape of a login code. Change only if you also change how codes are issued.                                                  |

If a setting is unsafe for production the service says so in its log at start-up ("Unsafe for production: …"). A clean start has no such lines.

## 5. Start the service

```bash
sudo cp deploy/eliddi-backend.service /etc/systemd/system/
sudo cp deploy/eliddi-backup.service deploy/eliddi-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eliddi-backend eliddi-backup.timer
systemctl status eliddi-backend
curl http://127.0.0.1:8000/          # Hello from ELiDDI_backend
```

The first start creates the database and applies its migrations. The service runs gunicorn, **not** Flask's development server, and never in debug mode.

## 6. Put nginx and HTTPS in front

```bash
sudo cp deploy/nginx-eliddi.conf /etc/nginx/conf.d/eliddi.conf
sudo nano /etc/nginx/conf.d/eliddi.conf     # your host name and certificate paths
sudo nginx -t
sudo setsebool -P httpd_can_network_connect 1     # SELinux: let nginx reach 127.0.0.1:8000
sudo firewall-cmd --permanent --add-service=http --add-service=https
sudo firewall-cmd --reload
sudo systemctl enable --now nginx
```

The nginx file sets `X-Forwarded-For` to the client's address rather than appending to what the client sent. That, with `ELIDDI_PROXY_HOPS=1`, is what stops a Respondent (or an attacker) choosing the address the rate limit sees. If you put a second proxy or a load balancer in front, change `ELIDDI_PROXY_HOPS` to match.

Check it from another machine:

```bash
curl https://diary.example.org/                                   # Hello from ELiDDI_backend
curl -i -X OPTIONS https://diary.example.org/state -H 'Origin: https://stratus.github.io'
#   → Access-Control-Allow-Origin: https://stratus.github.io     (your own origin: must appear)
curl -i -X OPTIONS https://diary.example.org/state -H 'Origin: https://other.example'
#   → no Access-Control-Allow-Origin line                         (anyone else: must not)
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://diary.example.org/submit \
     -H 'Content-Type: application/json' -d '{}'
#   → 401                                                          (no login: refused)
```

## 7. Issue login codes

A Respondent logs in with a code. How real codes will reach Respondents (probably by email) is not decided yet, so there is no automatic issuing. Until it is, make codes with the admin command, which prints them **once**; only a hash is stored, so a lost list cannot be recovered (make new Respondents instead):

```bash
sudo -u eliddi /opt/eliddi-backend/deploy/eliddi-admin create-respondents 50 > codes.txt
```

Pass the codes on by whatever means your study uses, then delete `codes.txt` (`shred -u codes.txt`). Run the command again for more; each run adds new Respondents.

Then try the whole thing with a real code: open the study page, log in, enter an Entry, reload and check it is still there.

## 8. Day to day

|                     |                                                                                            |
| ------------------- | ------------------------------------------------------------------------------------------ |
| Is it running?      | `systemctl status eliddi-backend`                                                          |
| Application log     | `journalctl -u eliddi-backend` (add `-f` to follow, `--since today` to narrow)             |
| nginx logs          | `/var/log/nginx/access.log` and `error.log`                                                |
| Restart             | `sudo systemctl restart eliddi-backend` (picks up changes to `/etc/eliddi-backend.env`)     |
| Backup log          | `journalctl -u eliddi-backup`; next run: `systemctl list-timers eliddi-backup.timer`       |
| How many Diaries?   | see [Looking at the data](#looking-at-the-data)                                            |

The journal's own retention settings decide how long the application log is kept. The log contains client addresses (from nginx) and no login codes, tokens or diary contents.

### Looking at the data

```bash
sudo -u eliddi /opt/eliddi-backend/venv/bin/python -c "
import sqlite3
c = sqlite3.connect('/var/lib/eliddi/eliddi.sqlite3')
print('respondents:', c.execute('select count(*) from respondents').fetchone()[0])
print('submitted diaries:', c.execute('select count(*) from submissions').fetchone()[0])
print('saved in-progress diaries:', c.execute('select count(*) from diary_states').fetchone()[0])"
```

Submitted Diaries are in the `submissions` table, each as the JSON the page sent (`payload`) with the Respondent, experiment, date and time beside it.

### Exporting the data

On the server, as the service user:

```bash
sudo -u eliddi /opt/eliddi-backend/deploy/eliddi-admin export-submissions > export.json
sudo -u eliddi /opt/eliddi-backend/deploy/eliddi-admin export-submissions --experiment stratus --output export.json
```

The file has `exportedAt`, `count` and a `submissions` list in the order they arrived. Each entry is `id`, `respondentId` (an opaque id, never a login code), `experimentID`, `date`, `status` (`0` in progress, `100` complete), `submittedAt`, `latest` and the `payload` exactly as the page sent it ([ADR 0006](https://github.com/CentreforTimeUseResearch/ELiDDI/blob/main/docs/adr/0006-diary-submission-payload.md)).

A Diary can be submitted more than once (the first goes out in progress, the finished day again as complete), so each row says whether it is the `latest` one for that Respondent, experiment and date. **Keep only the rows where `latest` is true to get one Diary per day.**

### Giving a researcher the data

A researcher with no access to the server can download the same file from the running service. **This is a temporary stopgap for one researcher in a small test**, until there is a real admin system: one shared password, no per-person login, no audit trail, and the whole export is built in memory.

1. Make a password and put it in `/etc/eliddi-backend.env`:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(24))"
   sudo nano /etc/eliddi-backend.env        # ELIDDI_EXPORT_PASSWORD=<the string>
   sudo systemctl restart eliddi-backend
   ```

2. Send the researcher the password (not in the same message as the address), and this address:

   ```
   https://<your server>/admin/export                       every study on this server
   https://<your server>/admin/export?experimentID=stratus  one study
   ```

   Their browser asks for a username and password: any username, and the password above. The file `eliddi-export-<date>.json` is then saved. From a terminal: `curl -u researcher:<password> -OJ "https://<your server>/admin/export"`.

3. When they are done, **remove the line from the settings file and restart** (the route then answers `404`), or change the password to cut off the old one.

Safeguards: it is only reachable over HTTPS (nginx redirects port 80); the password is compared in constant time; wrong passwords share the per-address limit of login codes (`ELIDDI_LOGIN_MAX_FAILURES` / `ELIDDI_LOGIN_WINDOW`) and then get `429`; the response is sent with `Cache-Control: no-store`. The service logs a warning at start-up if the password is shorter than 16 characters. Check the nginx access log does not record request headers (the example config does not); the password travels in the `Authorization` header, never in the URL.

## 9. Backups and restore

The nightly timer (02:30) runs `deploy/backup.sh` as the `eliddi` user. It writes a consistent copy of the database, plus `code_hash_key` if the key is a file, to `/var/backups/eliddi/<timestamp>/` and deletes backups older than 30 days (`KEEP_DAYS`). Run one by hand with `sudo systemctl start eliddi-backup`.

**Copy `/var/backups/eliddi` off the server** with your centre's usual backup. A backup on the same disk does not survive the disk. The backups contain Respondents' diaries: protect them like the database itself.

**Restore:**

```bash
sudo systemctl stop eliddi-backend
sudo cp /var/lib/eliddi/eliddi.sqlite3 /var/lib/eliddi/eliddi.sqlite3.before-restore    # keep what is there, just in case
sudo cp /var/backups/eliddi/<timestamp>/eliddi.sqlite3 /var/lib/eliddi/eliddi.sqlite3
sudo chown eliddi:eliddi /var/lib/eliddi/eliddi.sqlite3
sudo systemctl start eliddi-backend
```

If the code hash key was kept in `ELIDDI_CODE_HASH_KEY`, it is already in your settings file. If it was the `code_hash_key` file, restore that too. Restoring loses what was saved after the backup was taken: Respondents carry on from their device's own copy and the next save puts it back, but a Diary that was only ever on the server since then is gone.

## 10. Upgrading

```bash
sudo -u eliddi /opt/eliddi-backend/deploy/backup.sh          # always first
cd /opt/eliddi-backend
sudo git pull                                                # or: git checkout <version>
sudo venv/bin/pip install -r requirements.txt
sudo systemctl restart eliddi-backend
journalctl -u eliddi-backend -n 30                           # a clean start, no errors
```

Database changes are plain SQL files in `app/migrations/`, applied automatically in order when the service starts, each in its own transaction. **A migration cannot be undone**, and the service refuses to start against a database that is newer than its code. To go back: stop the service, restore the backup you took (section 9), check out the old code, start it.

## Production checklist

Before the first real Respondent logs in, check each of these:

- [ ] `ELIDDI_DUMMY_RESPONDENTS` is **not** set, and there is no `dummy_codes.json` in `/var/lib/eliddi` (it holds codes in plain text; delete it if it is there).
- [ ] `ELIDDI_REQUIRE_AUTH=1`.
- [ ] `ELIDDI_CORS_ORIGINS` lists only the study page origins, not `*`.
- [ ] `ELIDDI_PROXY_HOPS=1` and nginx **sets** `X-Forwarded-For` as in `deploy/nginx-eliddi.conf`.
- [ ] Served over HTTPS only; port 8000 is not reachable from outside (`ss -ltn` shows it on `127.0.0.1`).
- [ ] The code hash key is in your records, and `/var/backups/eliddi` is copied off the server.
- [ ] `ELIDDI_EXPORT_PASSWORD` is unset unless a researcher is using the export right now, and is 16+ random characters when it is set.
- [ ] `journalctl -u eliddi-backend` shows no "Unsafe for production" lines.
- [ ] The three `curl` checks in section 6 give the answers shown.
- [ ] You have logged in with a real code from the real study page and the diary survived a reload.

## What is not decided or built yet

- **How real login codes are issued.** `create-respondents` is the stopgap. Lost-code handling (a Respondent who loses their code) is part of the same open question ([ELiDDI_backend#2](https://github.com/CentreforTimeUseResearch/ELiDDI_backend/issues/2)).
- **A real admin system for researchers** (per-person logins, an audit trail, paging, a view as well as a download). The export above is a command plus a temporary shared-password route ([ELiDDI_backend#9](https://github.com/CentreforTimeUseResearch/ELiDDI_backend/issues/9)); whether an admin view is wanted is still to be confirmed with Lausanne.
- **Data retention and deletion** are your centre's and the study's decisions. The data is in one SQLite file, so a Respondent's rows can be found by their id.
- **Login lifetime** is the 12-hour proposal in [ELiDDI's ADR 0007](https://github.com/CentreforTimeUseResearch/ELiDDI/blob/main/docs/adr/0007-server-sync-model.md); confirm it for the study.

## If something is wrong

| You see                                                       | Likely cause                                                                                              |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `502 Bad Gateway` from nginx                                  | The service is down (`systemctl status eliddi-backend`) or SELinux blocks nginx (`setsebool` in section 6; `sudo ausearch -m avc -ts recent`). |
| Pages cannot log in; the browser console says CORS            | The study page's origin is not in `ELIDDI_CORS_ORIGINS` (exact scheme and host, no path, no trailing slash needed). Restart after editing. |
| Every Respondent gets `429` after a few wrong codes together  | `ELIDDI_PROXY_HOPS` is `0` behind nginx, so everyone shares the proxy's address. Set it to `1`.            |
| Every code stops working after a restart or restore           | The code hash key changed. Put the original in `ELIDDI_CODE_HASH_KEY`.                                    |
| The service will not start, log says the database is newer    | The code is older than the database. Update the code, or restore a backup (section 10).                   |
| `database is locked` in the log                               | Something else has the file open for writing (a stray editor or a long query). Close it; the app retries for 10 seconds. |
