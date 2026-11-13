# Dev environment on Verda

The core service runs from the `dev` branch on one small Verda instance in Finland. Every change is tested there before it reaches `main`.

- **URL:** https://sentti.jeremyxd.dev (`/healthz`, `/readyz`, and later `/api/*`). The old name `135-181-63-178.sslip.io` still answers until PR #54 is merged (see "Changing the host name").
- **Deploy:** `bash deploy/dev.sh` deploys `origin/dev`.
- **Routing:** Caddy sends only `/api/*`, `/healthz` and `/readyz` to the core service. Every other path is a plain 404 until the app is served from the same host. FastAPI's `/docs` is not exposed.

## What runs where

| Item | Value |
|---|---|
| Instance | `shadowless1-dev`, id `eaaa3b3f-b9a6-4737-acb2-21450653f16f` |
| Type | `CPU.4V.16G`: 4 vCPU, 16 GB RAM, no GPU (the smallest CPU type Verda offers) |
| Region | `FIN-01` (Finland, EU) |
| Image | `24.04.base` (Ubuntu 24.04) |
| OS volume | 50 GB NVMe, id `89a421bb-0c81-4479-bef8-24a075f70eaa`. 50 GB is the platform default; a 30 GB request was rejected ("storage size is too low"). |
| Address | `135.181.63.178`; public name `sentti.jeremyxd.dev` (a Cloudflare A record in "DNS only" mode, no proxy). `135-181-63-178.sslip.io` (sslip.io resolves it to the IP) also answers for now. |
| SSH key at Verda | `shadowless1-dev-deploy` |

The request travels like this:

1. GitHub (`dev` branch)
2. `git fetch` on the instance, using a read-only deploy key
3. `docker build` on the instance
4. systemd unit `shadowless1-core`: one container, one uvicorn worker, listening on `127.0.0.1:8000`
5. Caddy on ports 80 and 443, which serves HTTPS and proxies to the container

Nothing is uploaded from a developer's machine. The instance pulls the code itself, so `dev.sh` can only deploy commits that are pushed to GitHub.

## Cost and how to stop it

| Part | Price |
|---|---|
| Instance `CPU.4V.16G`, pay-as-you-go | 0.048 USD/h |
| OS volume, 50 GB NVMe at 0.20 USD per GB-month | about 0.014 USD/h |
| **Total** | **about 0.062 USD/h, about 1.48 USD/day (about 45 USD/month)** |

**Billing runs until both the instance and its volume are deleted.** Shutting the instance down does not stop the charge.

Delete both in one call. This needs `VERDA_CLIENT_ID` and `VERDA_CLIENT_SECRET` from `.env` exported in the shell. Everything runs inside one Python process, so neither the secret nor the access token appears on a command line, in the process list, in shell history or in the output:

```bash
set -a && . ./.env && set +a
python - <<'EOF'
import json, os, urllib.request

API = "https://api.verda.com/v1"

def call(method, path, body=None, token=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return r.status, json.loads(raw) if raw else None

_, auth = call("POST", "/oauth2/token", {"grant_type": "client_credentials",
                                         "client_id": os.environ["VERDA_CLIENT_ID"],
                                         "client_secret": os.environ["VERDA_CLIENT_SECRET"]})
token = auth["access_token"]
status, result = call("PUT", "/instances", {"action": "delete", "id": ["eaaa3b3f-b9a6-4737-acb2-21450653f16f"],
                                            "volume_ids": ["89a421bb-0c81-4479-bef8-24a075f70eaa"],
                                            "delete_permanently": True}, token)
print("delete:", status, result)
print("instances left:", call("GET", "/instances", token=token)[1])   # expect []
print("volumes left:", call("GET", "/volumes", token=token)[1])       # expect []
EOF
```

In the console (https://console.verda.com), delete the instance and tick the option to delete its OS volume. Then check that the Volumes page is empty.

## Deploy

```bash
bash deploy/dev.sh                          # origin/dev (default)
bash deploy/dev.sh r/17-verda-dev-deploy    # a pushed branch, for a smoke test
bash deploy/dev.sh <commit-sha>             # an exact commit, e.g. to roll back
```

`dev.sh` connects as root with `~/.ssh/shadowless1_dev_ed25519` (override with `DEV_SSH_KEY`). On the instance it runs these steps:

1. `git fetch`, then a detached checkout of the commit.
2. `deploy/remote-deploy.sh` from that commit:
   - builds the image `shadowless1-core:<sha>`;
   - refuses an image that contains `.env`, `.git` or tests;
   - **import check**: runs the image once without network. It must import and build the application (`core.app.main.create_app()`) and import every module of `core/tools` and `core/agent` (when present). When the tools read metric SQL it must also hold `core/metrics/*.sql`. If not, the deploy stops here and the running version stays untouched;
   - switches the service to the new image;
   - waits up to 30 s for `/healthz`;
   - renders the Caddy config and reloads Caddy;
   - records the deploy in `/opt/shadowless1/deploy.log`.
3. Back on your machine, `dev.sh` checks `GET https://sentti.jeremyxd.dev/healthz` (override with `DEV_URL`) and fails unless it gets 200.

`/readyz` is not a deploy gate: it is 503 whenever the database is unreachable, and that should not block a deploy.

`origin/dev` can be deployed once it contains `deploy/` (PR #54). Before that, `dev.sh` stops with "commit … predates the deploy files" and leaves the running version untouched.

On the first deploy to a new host name, Caddy needs a few seconds to obtain the certificate, so the public check retries for up to a minute.

Example run (the smoke test of this branch, before the host switch, so it checks the sslip.io name):

```
deploying 'r/17-verda-dev-deploy' to 135.181.63.178
checked out 0177340 Route only /api, /healthz and /readyz to the core service (#17)
== building 0177340763e5b2ce7121822a37b4e544143f98bc (previous: 1e395dc61dd5447d85e1d6de5b39a0de06b0c681)
== image contents (must not hold .env, .git or tests)
. ./core ./core/app ./core/app/__init__.py ./core/app/db.py ./core/app/health.py ./core/app/main.py ./core/app/settings.py ./core/requirements.txt
== starting
== proxy
deployed 0177340763e5b2ce7121822a37b4e544143f98bc; local /healthz: {"status":"ok","demo_today":"2026-09-30"}
public check: https://135-181-63-178.sslip.io/healthz
GET https://135-181-63-178.sslip.io/healthz -> 200
```

## Roll back

If a new version fails to start (`systemctl restart` fails), or does not pass `/healthz` within 30 s, `remote-deploy.sh` switches back to the previous commit by itself and exits with an error. It restores both that commit's image and **its** unit file, taken from git, so a broken unit change cannot break the rollback too.

The deployed commit is recorded in `/opt/shadowless1/current` right after it passes `/healthz`, before the proxy step. So even if the Caddy config turns out invalid, which the script prints and stops on, the next deploy knows the right "previous".

To go back by hand to the commit before the current one:

```bash
ssh -i ~/.ssh/shadowless1_dev_ed25519 root@135.181.63.178 tail -5 /opt/shadowless1/deploy.log
bash deploy/dev.sh <previous-sha>
```

The images of the current and the previous deploy stay on the instance, so a rollback to the previous commit needs no rebuild.

To test the automatic rollback without a broken commit, point the deploy gate at a path that does not exist:

```bash
DEV_HEALTH_PATH=/no-such-path bash deploy/dev.sh r/17-verda-dev-deploy
```

The new image starts, the gate gets 404 for 30 s, and the script prints the last log lines (masked) and switches back:

```
new version is not healthy (GET /no-such-path); last log lines (masked):
INFO:     x.x.x.x:41302 - "GET /no-such-path HTTP/1.1" 404 Not Found
...
switching back to 1e395dc61dd5447d85e1d6de5b39a0de06b0c681
previous version 1e395dc61dd5447d85e1d6de5b39a0de06b0c681 is running again
```

## Logs

The logs stay on the instance and are not shipped anywhere. The journal is readable only by root and the `adm`/`systemd-journal` groups.

```bash
ssh -i ~/.ssh/shadowless1_dev_ed25519 root@135.181.63.178 journalctl -u shadowless1-core -n 100 --no-pager   # service
ssh -i ~/.ssh/shadowless1_dev_ed25519 root@135.181.63.178 journalctl -u caddy -n 50 --no-pager              # proxy and TLS
```

The service writes only to the journal (the container runs with `--log-driver none`). Its access log lines contain client IP addresses. If a deploy fails, `remote-deploy.sh` prints the last 30 lines with a mask that errs on the side of hiding:
- A credential-looking key (also inside names such as `GEMINI_API_KEY` or `DB_PASSWORD`) followed by `:` or `=` hides everything to the end of the line, quotes and spaces included.
- A URL hides everything after its scheme.
- A line with `something@host.domain` is hidden as a whole.
- These are replaced:
  - `Bearer` tokens;
  - the word after `host`/`host name`/`server at`, quoted or not;
  - user names (`user=…`, `for user "…"`);
  - host names with common top-level domains;
  - IPv4 and IPv6 addresses. `127.0.0.1` and `0.0.0.0` stay readable, so "listening on" lines still make sense.

`bash deploy/remote-deploy.sh --self-test-mask` masks the sample lines built into the script. It exits 1 if any secret of a sample survives, or if a plain log line changes. Its output (run locally and on the instance):

```
ok   *** (line hidden: credentials at a host)          <- postgresql://u:p@ss@db.example.com/x?sslmode=require
ok   *** (line hidden: credentials at a host)          <- error: postgresql://u:p/ss@db.example.com:5432/x failed
ok   connection to server at "***" (x.x.x.x), port 5432 failed
ok   host=*** user=*** password= ***
ok   host='***' port=5432
ok   FATAL:  password authentication failed for user "***"
ok   connection failed: user = '***'
ok   INFO:     Uvicorn listening on 0.0.0.0:8000 and 127.0.0.1:8000
ok   GEMINI_API_KEY= ***
ok   MY_SERVICE_TOKEN= ***
ok   APP_SECRET= ***
ok   password = ***
ok   PASSWORD: ***
ok   api_key: ***
ok   Authorization: ***
ok   password= ***                                      <- password='s3 cret'
ok   *** (line hidden: credentials at a host)          <- u:"pa ss word"@db.example.com
ok   could not translate host name *** to address
ok   ***                                                <- db.example.com alone on a line
ok   connection to x:x::x refused
ok   listening on x:x::x and x:x::x
ok   GET /healthz?token= ***
ok   INFO:     Application startup complete.
ok   shadowless1-core.service: Main process exited, code=exited, status=1/FAILURE
mask self-test passed
```

The journal was checked after the real `DATABASE_URL` was set. Over 105 lines (a restart, the rollback test and a deploy), it contained no part of the URL: 0 matches for the full URL, host, user, password and `postgres://`.

## Settings on the instance

The service reads `/etc/shadowless1/core.env` every time it starts. The file is owned by root, mode 600, and lives outside git. Its variables:

| Variable | Notes |
|---|---|
| `DATABASE_URL` | the shared PostgreSQL |
| `DEMO_TODAY` | default `2026-09-30` |
| `GEMINI_API_KEY` | |
| `GEMINI_MODEL` | unset for now |
| `CORS_ORIGINS` | comma-separated; empty means the local dev servers. Add the app's origin here when it has a URL. |

Set now: `DATABASE_URL`, `DEMO_TODAY` and `GEMINI_API_KEY`. `GEMINI_MODEL` and `CORS_ORIGINS` are unset, so they take their defaults. They were written over SSH stdin, never on a command line, with quotes stripped; on the instance only the URL's shape was checked.

To change a setting, no redeploy is needed:

```bash
ssh -i ~/.ssh/shadowless1_dev_ed25519 root@135.181.63.178
nano /etc/shadowless1/core.env          # one KEY=value per line, no quotes
systemctl restart shadowless1-core
```

Write values without quotes. Docker's `--env-file` keeps quotes literally, and a quoted `DATABASE_URL` is a malformed URL.

## Access

- **SSH:** keys only. Root logs in with a key, and password login is off; check with `sshd -T`.
- **Private key:** the deploy machine's key is `~/.ssh/shadowless1_dev_ed25519`. It stays outside the repository.
- **Giving someone access:** a person who already has access appends the new member's public key:
  ```bash
  ssh -i ~/.ssh/shadowless1_dev_ed25519 root@135.181.63.178 'cat >> /root/.ssh/authorized_keys' < their_key.pub
  ```
- **Repository:** the instance reads the repository with a **read-only** deploy key, `shadowless1-dev-instance (Verda, read-only)` under GitHub → Settings → Deploy keys. Its private half exists only on the instance (`/root/.ssh/github_deploy`). Revoke it there when the instance is deleted.

## Security

- **Firewall:** `ufw` allows only 22, 80 and 443 (`ufw status`). Verda has no provider firewall for single instances.
- **Container port:** the container's port is published on `127.0.0.1` only. Docker's published ports bypass `ufw`, so a public binding would be open to everyone.
- **Container:** it runs as a non-root user, with a read-only file system, 1 GB memory and a pid limit.
- **Secrets:** no secret is in git, in the image or in deploy output. The image is built from the allowlist in `.dockerignore`:
  - `core/requirements.txt`;
  - `core/app`, `core/tools` and `core/agent` (the service, the tools and the answer pipeline);
  - `core/metrics/*.sql` (the metric SQL the tools run);
  - `core/config/*.yaml` (personas and benefit rules).

  Every `tests` directory and cache is excluded again after that, because later lines win. `deploy/Dockerfile` copies `core` as a whole, so the allowlist alone decides what goes in. A path in the list that does not exist yet (`core/agent`) is simply absent. A new runtime path is added to `.dockerignore` only, and the import check catches a forgotten one before the switch.

## Setting up a new instance from scratch

1. **Create the instance.** In the console or the API: `CPU.4V.16G`, `FIN-01`, image `24.04.base`, SSH key `shadowless1-dev-deploy`, the default OS volume, pay-as-you-go, not spot.
2. **Run the setup script:**
   ```bash
   git show HEAD:deploy/setup-instance.sh | ssh -i ~/.ssh/shadowless1_dev_ed25519 root@<ip> 'bash -s -- <ip>'
   ```
   It installs Docker, Caddy, ufw and git, closes every port except 22/80/443, turns off password login, prepares `/etc/shadowless1`, creates the instance's deploy key and prints its public half.
3. **Add the deploy key.** Add that public key in GitHub → repository Settings → Deploy keys, with **"Allow write access" unchecked**. Then run step 2 again; this time it clones the repository.
4. **Fill in the settings.** Write `/etc/shadowless1/core.env` (see "Settings on the instance").
5. **Deploy.** Run `bash deploy/dev.sh`.

If a TLS certificate cannot be issued (for example Let's Encrypt rate limits), serve plain HTTP: write the name with `http://` in front (for example `http://sentti.jeremyxd.dev`) to `/etc/shadowless1/site` and render the Caddy config again (see "Changing the host name").

## Changing the host name

The host name lives in one place on the instance: `/etc/shadowless1/site`, one line, outside git. It is now `135-181-63-178.sslip.io, sentti.jeremyxd.dev`: both names answer, and each has its own Let's Encrypt certificate.

`sentti.jeremyxd.dev` is a Cloudflare A record pointing at `135.181.63.178` in "DNS only" mode (no proxy), so Caddy gets its certificate itself (HTTP-01 challenge on port 80).

To change the names, edit that line and render the Caddy config again. No redeploy is needed.

**Add a new name only after its DNS record resolves to the instance**, because failed attempts count against Let's Encrypt rate limits:

```bash
dig +short sentti.jeremyxd.dev        # must print 135.181.63.178
ssh -i ~/.ssh/shadowless1_dev_ed25519 root@135.181.63.178 '
  echo "135-181-63-178.sslip.io, sentti.jeremyxd.dev" > /etc/shadowless1/site
  cd /opt/shadowless1/repo && sed "s|__SITE__|$(cat /etc/shadowless1/site)|" deploy/Caddyfile > /etc/caddy/Caddyfile.new &&
  caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile && mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile &&
  systemctl reload caddy'
```

When `sentti.jeremyxd.dev` was added, Caddy got its certificate on the first attempt, about 5 s after the reload. Checked from outside:

```
$ curl -s https://sentti.jeremyxd.dev/healthz
{"status":"ok","demo_today":"2026-09-30"}
$ curl -s -o /dev/null -w "%{http_code}" https://sentti.jeremyxd.dev/readyz
200
/ -> 404   /docs -> 404   /openapi.json -> 404
http://sentti.jeremyxd.dev/healthz -> 308 -> https://sentti.jeremyxd.dev/healthz
subject=CN=sentti.jeremyxd.dev
issuer=C=US, O=Let's Encrypt, CN=YE1
notAfter=Feb 11 20:35:54 2027 GMT
```

Once PR #54 is merged, the sslip.io name can be dropped. Write only `sentti.jeremyxd.dev` to the file and render again.

`CORS_ORIGINS` needs no change while the app calls `/api` on the same host. Add an origin there only when the app is served from a different one.
