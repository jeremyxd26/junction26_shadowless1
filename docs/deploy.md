# Dev environment on Verda

The core service runs from the `dev` branch on one small Verda instance in Finland. Every change is tested there before it reaches `main`.

- **URL:** https://135-181-63-178.sslip.io (`/healthz`, `/readyz`)
- **Deploy:** `bash deploy/dev.sh` deploys `origin/dev`.

## What runs where

| Item | Value |
|---|---|
| Instance | `shadowless1-dev`, id `eaaa3b3f-b9a6-4737-acb2-21450653f16f` |
| Type | `CPU.4V.16G`: 4 vCPU, 16 GB RAM, no GPU (the smallest CPU type Verda offers) |
| Region | `FIN-01` (Finland, EU) |
| Image | `24.04.base` (Ubuntu 24.04) |
| OS volume | 50 GB NVMe, id `89a421bb-0c81-4479-bef8-24a075f70eaa`. 50 GB is the platform default; a 30 GB request was rejected ("storage size is too low"). |
| Address | `135.181.63.178`; public name `135-181-63-178.sslip.io` (sslip.io resolves it to the IP) |
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

The account balance was 221.04 USD when the instance was created.

**Billing runs until both the instance and its volume are deleted.** Shutting the instance down does not stop the charge.

Delete both in one call. This needs `VERDA_CLIENT_ID` and `VERDA_CLIENT_SECRET` from `.env` exported in the shell; the token is never printed:

```bash
set -a && . ./.env && set +a
TOKEN=$(python - <<'EOF'
import json, os, urllib.request
body = json.dumps({"grant_type": "client_credentials", "client_id": os.environ["VERDA_CLIENT_ID"],
                   "client_secret": os.environ["VERDA_CLIENT_SECRET"]}).encode()
req = urllib.request.Request("https://api.verda.com/v1/oauth2/token", data=body,
                             headers={"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req))["access_token"])
EOF
)
curl -sS -X PUT https://api.verda.com/v1/instances \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data '{"action": "delete", "id": ["eaaa3b3f-b9a6-4737-acb2-21450653f16f"],
           "volume_ids": ["89a421bb-0c81-4479-bef8-24a075f70eaa"], "delete_permanently": true}'
curl -sS https://api.verda.com/v1/instances -H "Authorization: Bearer $TOKEN"   # expect []
curl -sS https://api.verda.com/v1/volumes   -H "Authorization: Bearer $TOKEN"   # expect []
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
   - switches the service to the new image;
   - waits up to 30 s for `/healthz`;
   - renders the Caddy config and reloads Caddy;
   - records the deploy in `/opt/shadowless1/deploy.log`.
3. Back on your machine, `dev.sh` checks `GET https://135-181-63-178.sslip.io/healthz` and fails unless it gets 200.

`/readyz` is not a deploy gate: it is 503 whenever the database is unreachable, and that should not block a deploy.

## Roll back

If a new version does not pass `/healthz` within 30 s, `remote-deploy.sh` switches back to the previous image by itself and exits with an error.

To go back by hand to the commit before the current one:

```bash
ssh -i ~/.ssh/shadowless1_dev_ed25519 root@135.181.63.178 tail -5 /opt/shadowless1/deploy.log
bash deploy/dev.sh <previous-sha>
```

The images of the current and the previous deploy stay on the instance, so a rollback to the previous commit needs no rebuild.

## Logs

The logs stay on the instance and are not shipped anywhere. The journal is readable only by root and the `adm`/`systemd-journal` groups.

```bash
ssh -i ~/.ssh/shadowless1_dev_ed25519 root@135.181.63.178 journalctl -u shadowless1-core -n 100 --no-pager   # service
ssh -i ~/.ssh/shadowless1_dev_ed25519 root@135.181.63.178 journalctl -u caddy -n 50 --no-pager              # proxy and TLS
```

The service writes only to the journal (the container runs with `--log-driver none`). If a deploy fails, `remote-deploy.sh` prints the last 30 lines with URLs and `password=`/`key=`/`token=` values masked.

## Settings on the instance

The service reads `/etc/shadowless1/core.env` every time it starts. The file is owned by root, mode 600, and lives outside git. Its variables:

| Variable | Notes |
|---|---|
| `DATABASE_URL` | the shared PostgreSQL |
| `DEMO_TODAY` | default `2026-09-30` |
| `GEMINI_API_KEY` | |
| `GEMINI_MODEL` | unset for now |
| `CORS_ORIGINS` | comma-separated; empty means the local dev servers. Add the app's origin here when it has a URL. |

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
- **Secrets:** no secret is in git, in the image or in deploy output. The image is built from the allowlist in `.dockerignore` (`core/app`, `core/requirements.txt`). A new runtime path, for example SQL files the API reads, must be added there and in `deploy/Dockerfile`.

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

If the TLS certificate cannot be issued (Let's Encrypt limits for sslip.io names), serve plain HTTP: write `http://135-181-63-178.sslip.io` to `/etc/shadowless1/site` and deploy again.
