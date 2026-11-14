# Dev environment on Verda

The core service runs from the `dev` branch on one small Verda instance in Finland. Every change is tested there before it reaches `main`.

- **URL:** https://sentti.jeremyxd.dev: the app at `/`, the core at `/api/*`, `/healthz` and `/readyz`. The old name `135-181-63-178.sslip.io` still answers until PR #54 is merged (see "Changing the host name").
- **Deploy:** `bash deploy/dev.sh` deploys `origin/dev`.
- **Routing:** Caddy sends only `/api/*`, `/healthz` and `/readyz` to the core service. Every other path is the app: the static build of `app/` for the deployed commit, with client routes such as `/chat` falling back to `index.html`. A commit without `app/package.json` serves no app, and those paths answer 404. FastAPI's `/docs` is not exposed (`/docs` is an app route that falls back to the app).

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
5. Caddy on ports 80 and 443, which serves HTTPS, proxies the core routes to the container and serves the app's static files from `/opt/shadowless1/app/current` (no Node on the request path)

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
   - **completeness check**: every tracked non-test file of the checkout under `core/app`, `core/tools`, `core/agent`, `core/bills` (`*.py`), the model prompts `core/agent/prompts/*.md`, `core/answer_text.py`, `core/metrics/*.sql`, `core/config/*.yaml` and the sample bills `core/bills/samples/*.png` and `samples.json` must be in the image. The expectation comes from the checkout, so a path left out of `.dockerignore` is caught even if nothing imports it yet. If git cannot list the files, or the list lacks `core/app/main.py`, the deploy is refused as well;
   - **import check**: runs the image once without network. It must import and build the application (`core.app.main.create_app()`) and import every module of `core/tools`, `core/agent` and `core/bills` (when present);
   - if either check fails, the deploy stops here, the refused image is removed and the running version stays untouched;
   - **app build** (when the commit has `app/package.json`; see "The app" below). It runs in a throwaway `node:22.21.1-slim` container from the commit's tracked files and is checked for secrets. A failed build or a secret match stops the deploy here too, with nothing switched;
   - makes sure `/var/lib/shadowless1/var` exists, the service's persistent `var/` (see "Service data");
   - switches the service to the new image;
   - waits up to 30 s for `/healthz`;
   - points `/opt/shadowless1/app/current` at the new app build, only now that the core is healthy (an atomic link swap). A commit without `app/package.json` removes the link;
   - renders the Caddy config and reloads Caddy;
   - keeps the images and app builds of the current and the previous deploy and removes older ones;
   - records the deploy in `/opt/shadowless1/deploy.log`.
3. Back on your machine, `dev.sh` checks `GET https://sentti.jeremyxd.dev/healthz` (override with `DEV_URL`) and fails unless it gets 200.

`/readyz` is not a deploy gate: it is 503 whenever the database is unreachable, and that should not block a deploy.

`origin/dev` can be deployed once it contains `deploy/` (PR #54). Before that, `dev.sh` stops with "commit … predates the deploy files" and leaves the running version untouched.

On the first deploy to a new host name, Caddy needs a few seconds to obtain the certificate, so the public check retries for up to a minute.

Example run (a branch deploy, with both checks before the switch):

```
deploying 'r/60-deploy-image-contents' to 135.181.63.178
checked out c648379 Check the image against the checkout's run-time files before the switch (#60)
== building c64837975d8c75f7438fdba08412482122fbfb80 (previous: 7ca4392f761dfcde2cf88c9925777c9982662d8f)
== image contents (must not hold .env, .git or tests)
. ./core ./core/app ./core/app/__init__.py ./core/app/db.py ./core/app/health.py ./core/app/main.py ./core/app/settings.py ./core/config ./core/config/personas.yaml ./core/config/s_group_benefits.yaml ./core/metrics ./core/requirements.txt ./core/tools (+ 17 files in core/tools, 7 in core/metrics)
all run-time files of the checkout are in the image
== import check
imports ok: core.app and 16 modules of core.tools/core.agent
== starting
== proxy
deployed c64837975d8c75f7438fdba08412482122fbfb80; local /healthz: {"status":"ok","demo_today":"2026-09-30"}
public check: https://sentti.jeremyxd.dev/healthz
GET https://sentti.jeremyxd.dev/healthz -> 200
```

### Check the demo path after a deploy

After `bash deploy/dev.sh` (and before the demo), run:

```
python scripts/demo_check.py --base-url https://sentti.jeremyxd.dev --require-all --no-ask   # no model calls
python scripts/demo_check.py --base-url https://sentti.jeremyxd.dev --require-all            # plus the four brief questions
```

Every stage is live on dev now, so use `--require-all`: a stage that answers NOT DEPLOYED then fails the check.

The script checks, against the reference values at its top (`docs/design/personas.md`, `contracts/api.md`):
- health;
- the personas;
- Sanna's overview, and that its evidence refs resolve and reconcile;
- the persona allowlist;
- the what-if;
- the spike review ("Needed", then undo);
- optionally `/api/ask`.

It prints one line per stage: PASS, FAIL (expected and received), or NOT DEPLOYED (with the route and status). It exits 1 on any FAIL.

It uses the standard library only and needs no secrets. It never retries, and the whole run ends within `--time-limit` seconds (default 60).

The only writes are the label answer and its undo. The undo always runs and is always checked. If it fails, the script prints `UNDO FAILED - CUST00860 may be left answered`, with the `tx_ref` and the repair. The reliable repair is `python core/scripts/reset_reviews.py CUST00860`: with per-viewer answers, a bare curl acts as another viewer.

Without `--no-ask` it sends up to four questions to the model (`--ask-limit N` caps them) and stops at a 429. Do not run it in a loop.

## The app

`app/` is a static Vite build. Every deploy of a commit that contains `app/package.json` builds it on the instance; there is no artefact upload from a working directory:

- `git archive <sha> app` gives the commit's tracked files only. A local `app/.env` never reaches the build.
- They are built in a throwaway `node:22.21.1-slim` container: `npm ci && npm run build`, as uid 1000, with `--memory 2g`, `--cap-drop ALL` and `--security-opt no-new-privileges`. The container has network, because npm downloads the packages. npm's cache is kept in `/var/cache/shadowless1/npm`.
- The container gets no service setting. Its only build setting is the public `VITE_API_MODE=live`, so the app calls `/api` on the same origin. Vite puts only `VITE_*` variables into the bundle.
- Measured on this instance (4 vCPU) with the app of PR #75: 7 s with an empty npm cache, 6 s with a warm one. The build is about 0.3 MB in 3 files.
- **Only plain files.** The build must hold nothing but regular files and directories; a symbolic link or anything else refuses the deploy. Caddy follows links, so a link left in the build by a package could otherwise publish any file Caddy can read, its TLS keys included.
- **Secret check.** The secret-like settings of `/etc/shadowless1/core.env` (names ending in `KEY`, `TOKEN`, `SECRET` or `PASSWORD`, and `DATABASE_URL`) are searched for in all built files: the full value when it has at least 6 characters, and a URL's password and host. Any match refuses the deploy and prints the setting's name, never its value. Public settings such as a model name, CORS origins or a plain URL are not searched.
- The result is installed as `/opt/shadowless1/app/<sha>` (root-owned, world-readable). The link `/opt/shadowless1/app/current` moves to it after the core passed `/healthz`, so a failed build, a failed check or a failed core start leaves the previous app and core serving. A commit whose build is already installed (a redeploy of the same commit, or a rollback to the previous one, whose build is kept) reuses it without npm, so the directory being served is never replaced.

**Caching** (`deploy/Caddyfile`):
- `/assets/*` holds Vite's content-hashed files: an existing file gets `Cache-Control: public, max-age=31536000, immutable`. A missing asset and the directory `/assets/` itself are a plain 404 with `no-store`, never `index.html`.
- Every other path: `Cache-Control: no-cache`, so `index.html` is revalidated on every load and a deploy shows at once.

A commit without `app/package.json` (any commit before PR #75 merged the app) prints `this commit has no app/package.json: no app build …`. The deploy removes the app link, so the paths outside the core answer 404 as before.

## Service data (`var/`)

The core writes its own data under `var/` at the repository root, which is `/srv/var` in the container: the audit log, the daily model-call counter (#85) and the response and tool caches (#86). The container's file system is read-only, and this one directory is a bind mount from the host:

| Host path | Container path | Owner, mode |
|---|---|---|
| `/var/lib/shadowless1/var` | `/srv/var` | uid 10001 (the container user `app`), `700` |

The answer pipeline's audit log goes to `/srv/var/audit` by default (`AUDIT_LOG_DIR` overrides it), so it lands in this directory. It survives deploys, rollbacks and restarts. `remote-deploy.sh` creates it before every switch (`install -d -o 10001 -g 10001 -m 700`), and only root and the container user can read it. To reset the counter or the caches, stop the service, delete the files and start it again.

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

The service masks the values of its secret settings as `***` in every log line, whichever logger writes it (`core/app/secret_mask.py`, #198). Secret settings are the names ending in `KEY`, `TOKEN`, `SECRET` or `PASSWORD`, and `DATABASE_URL`, together with its password and every host (in any connection-string form libpq accepts; loopback names excepted) and the URL-encoded forms of each. The mask covers the message and its arguments (the access log's request line included), extra fields and exception text with chained causes. A settings error at start-up names the setting but never echoes its value.

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
| `DB_POOL_MAX` | the pool's most connections, 1 to 20; unset means 10 (the shared database allows 100) |
| `API_DOCS` | leave unset: the interactive API docs stay off on the dev host (`1` is for local development) |

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
  - `core/answer_text.py`, the one module outside those packages that they import (the answer pipeline shares it with the eval);
  - `core/metrics/*.sql` (the metric SQL the tools run);
  - `core/config/*.yaml` (personas and benefit rules);
  - `core/bills` (the bill parser and the sample bills of the gallery; their PDFs and README stay out).

  Every `tests` directory and cache is excluded again after that, because later lines win. `deploy/Dockerfile` copies `core` as a whole, so the allowlist alone decides what goes in. A path in the list that does not exist yet (`core/agent`) is simply absent. A new file of a kind the completeness check already lists (`*.py` under `core/app`, `core/tools` or `core/agent`, `core/metrics/*.sql`, `core/config/*.yaml`) only needs its path in `.dockerignore`, and the check catches a forgotten one before the switch. A new **kind** of run-time file (for example `core/data/*.csv`) must be added to `.dockerignore` **and** to the `git ls-files` patterns of the completeness check in `deploy/remote-deploy.sh`; otherwise the check cannot see it.
- **Request size** (`deploy/Caddyfile`, #210): the API routes accept bodies up to 65536 bytes, 64 KiB (`request_body { max_size 64KiB }`; Caddy reads `KB` as 1000 bytes). The largest legitimate body is a question of 500 characters in a small JSON envelope. A larger request gets 413 from Caddy itself, with the security headers below and no `Server` header. A request whose `Content-Length` is over 65536 (leading zeros included) is refused before any byte goes to the service. A body without a `Content-Length` (HTTP/1.1 chunked, or an HTTP/2 or HTTP/3 stream) is cut off at 65536 bytes by `request_body`; the service then sees a client disconnect, and the client gets 413. Caddy 2.6 reports that case as a 502 inside the proxy, and `handle_errors` maps it to 413, while other 502s (the core down) stay 502.
- **Response headers** (`deploy/Caddyfile`, #102):

  | Applies to | Header |
  |---|---|
  | every response | `Strict-Transport-Security: max-age=31536000` (no `preload`: the parent domain is shared), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`; the `Server` header is removed, also the core's `server: uvicorn` |
  | `/api/*`, `/healthz`, `/readyz` (JSON) | `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` |
  | the app (`index.html` and the other non-asset paths) | `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'` |

  The app's policy follows the app owner's needs on #102: the Vite build emits external script and style files, no inline script, and the font is bundled. The app calls `/api` on its own origin. Images come from the app or `data:` URIs, so rendered markdown cannot load an outside image. Only the app's own origin may frame it; the S-mobiili WebView loads the module top-level and is not affected. A demo page on another origin that frames the app needs that origin added to `frame-ancestors`.

  After every deploy `dev.sh` checks the public URL and fails if HSTS or `nosniff` is missing. A deploy of a commit older than #102 therefore ends with that error, although the commit is running. To check by hand:
  ```
  curl -sS -D - -o /dev/null https://sentti.jeremyxd.dev/api/personas
  ```

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
