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
#   DEV_URL      public base URL         (default https://135-181-63-178.sslip.io)
# Prints no secret: the service settings stay in /etc/shadowless1/core.env on the instance.
set -euo pipefail

ref=${1:-dev}
[[ $ref =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "unsupported ref: $ref" >&2; exit 1; }
host=${DEV_HOST:-135.181.63.178}
key=${DEV_SSH_KEY:-$HOME/.ssh/shadowless1_dev_ed25519}
url=${DEV_URL:-https://135-181-63-178.sslip.io}
[[ -f $key ]] || { echo "SSH key not found: $key (see docs/deploy.md, 'Access')" >&2; exit 1; }

echo "deploying '$ref' to $host"
ssh -i "$key" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 \
    -o StrictHostKeyChecking=accept-new "root@$host" "bash -s -- '$ref'" <<'REMOTE'
set -euo pipefail
ref=$1
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
exec bash deploy/remote-deploy.sh "$sha"
REMOTE

echo "public check: $url/healthz"
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$url/healthz" || true)
echo "GET $url/healthz -> $code"
[[ $code == 200 ]]
