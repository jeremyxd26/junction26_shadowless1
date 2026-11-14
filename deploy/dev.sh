#!/usr/bin/env bash
# Deploy a pushed git ref to the dev instance. The instance pulls the code from GitHub itself
# (read-only deploy key); nothing from this working directory is uploaded.
#
#   bash deploy/dev.sh                     # deploy origin/dev (the default)
#   bash deploy/dev.sh r/17-verda-dev-deploy   # deploy a pushed branch (smoke tests)
#   bash deploy/dev.sh <commit-sha>        # deploy an exact commit, e.g. to roll back
#
# Settings (environment variables, all optional):
#   DEV_HOST     instance address        (default 135.181.63.178)
#   DEV_SSH_KEY  private key for root@   (default ~/.ssh/shadowless1_dev_ed25519; never commit it)
#   DEV_URL      public base URL         (default https://sentti.jeremyxd.dev)
#   DEV_HEALTH_PATH  deploy gate path    (default /healthz; a missing path such as /no-such-path makes the
#                                         gate fail on purpose, to test the automatic rollback)
# Prints no secret: the service settings stay in /etc/shadowless1/core.env on the instance.
set -euo pipefail

ref=${1:-dev}
[[ $ref =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "unsupported ref: $ref" >&2; exit 1; }
host=${DEV_HOST:-135.181.63.178}
key=${DEV_SSH_KEY:-$HOME/.ssh/shadowless1_dev_ed25519}
url=${DEV_URL:-https://sentti.jeremyxd.dev}
health_path=${DEV_HEALTH_PATH:-/healthz}
[[ $health_path =~ ^/[A-Za-z0-9._/-]*$ ]] || { echo "unsupported health path: $health_path" >&2; exit 1; }
[[ -f $key ]] || { echo "SSH key not found: $key (see docs/deploy.md, 'Access')" >&2; exit 1; }

echo "deploying '$ref' to $host"
ssh -i "$key" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 \
    -o StrictHostKeyChecking=accept-new "root@$host" "bash -s -- '$ref' '$health_path'" <<'REMOTE'
set -euo pipefail
ref=$1
health_path=$2
cd /opt/shadowless1/repo
git fetch --quiet --prune origin
# A branch name is taken from origin; anything else must be a commit that origin has.
if sha=$(git rev-parse --quiet --verify "refs/remotes/origin/$ref^{commit}"); then :;
elif sha=$(git rev-parse --quiet --verify "$ref^{commit}"); then :;
else echo "ref not found on origin: $ref" >&2; exit 1; fi
git checkout --quiet --force --detach "$sha"
echo "checked out $(git log -1 --format='%h %s')"
if [[ ! -f deploy/remote-deploy.sh || ! -f deploy/Dockerfile ]]; then
  echo "commit $sha has no deploy/remote-deploy.sh or deploy/Dockerfile: it predates the deploy files" >&2
  exit 1
fi
exec bash deploy/remote-deploy.sh "$sha" "$health_path"
REMOTE

# The first deploy on a new name waits for the TLS certificate, so the public check retries for a minute.
echo "public check: $url/healthz"
for _ in $(seq 1 12); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$url/healthz" 2>/dev/null || true)
  [[ $code == 200 ]] && break
  sleep 5
done
echo "GET $url/healthz -> $code"
[[ $code == 200 ]]

# Security headers (#102, deploy/Caddyfile): HSTS and nosniff must come back from the public URL. A
# deploy of a commit older than #102 serves without them and fails here, although it is running.
headers=$(curl -sS -D - -o /dev/null --max-time 10 "$url/healthz" 2>/dev/null | tr -d '\r' || true)
missing=""
grep -qi '^strict-transport-security: max-age=' <<<"$headers" || missing+=" Strict-Transport-Security"
grep -qi '^x-content-type-options: nosniff' <<<"$headers" || missing+=" X-Content-Type-Options"
grep -qi '^cache-control: no-store' <<<"$headers" || missing+=" Cache-Control:no-store"   # #272, API routes
if [[ -n $missing ]]; then
  echo "security headers missing on $url/healthz:$missing" >&2
  exit 1
fi
echo "security headers present: Strict-Transport-Security, X-Content-Type-Options, Cache-Control: no-store"

# The sample bill images (#249) are the one API path cached for long: the listing stays no-store, and an
# image URL from it (with the image's hash) answers immutable for a year, with the security headers.
# A commit without the gallery has no listing (404), and the check is skipped.
listing=$(curl -sS -D - --max-time 10 "$url/api/bill/samples" 2>/dev/null | tr -d '\r' || true)
if grep -q '^HTTP/[0-9.]* 200' <<<"$listing"; then
  image=$(grep -o '"image_url":"[^"]*"' <<<"$listing" | head -1 | cut -d'"' -f4)
  image_headers=$(curl -sS -D - -o /dev/null --max-time 10 "$url$image" 2>/dev/null | tr -d '\r' || true)
  missing=""
  grep -qi '^cache-control: no-store' <<<"$listing" || missing+=" listing:Cache-Control:no-store"
  [[ -n $image ]] || missing+=" listing:image_url"
  grep -qi '^cache-control: public, max-age=31536000, immutable' <<<"$image_headers" || missing+=" image:Cache-Control"
  grep -qi '^x-content-type-options: nosniff' <<<"$image_headers" || missing+=" image:X-Content-Type-Options"
  if [[ -n $missing ]]; then
    echo "sample bill caching wrong:$missing" >&2
    exit 1
  fi
  echo "sample bills: listing no-store; $image cached for a year (immutable)"
else
  echo "no /api/bill/samples in this commit: sample image cache check skipped"
fi
