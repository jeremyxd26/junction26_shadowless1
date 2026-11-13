#!/usr/bin/env bash
# Runs ON the dev instance as root, from /opt/shadowless1/repo already checked out at <sha>.
# Called by deploy/dev.sh; not meant to be run by hand except for debugging.
# Builds the image for <sha>, switches the service to it, waits for /healthz, renders the Caddy config.
# If the new version does not become healthy, it switches back to the previous image.
# Never prints the settings file or environment values; failure logs are masked.
set -euo pipefail

sha=${1:?usage: remote-deploy.sh <commit-sha>}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "not a full commit sha: $sha" >&2; exit 1; }
cd /opt/shadowless1/repo
state=/opt/shadowless1
prev=$(cat "$state/current" 2>/dev/null || echo none)

mask() { sed -E 's#([a-zA-Z][a-zA-Z0-9+.-]*://)[^ @/]*@#\1***@#g; s#(password|secret|key|token)=[^ &]*#\1=***#Ig'; }

echo "== building $sha (previous: $prev)"
docker build --quiet --file deploy/Dockerfile --tag "shadowless1-core:$sha" . >/dev/null

echo "== image contents (must not hold .env, .git or tests)"
listing=$(docker run --rm --entrypoint sh "shadowless1-core:$sha" -c 'cd /srv && find . -maxdepth 3 -not -path "*/__pycache__*" | sort')
echo "$listing" | tr '\n' ' '; echo
if grep -qE '(^|/)(\.env|\.git|tests)(/|$)' <<<"$listing"; then
  echo "refusing to deploy: the image contains .env, .git or tests" >&2
  exit 1
fi

switch_to() {
  docker tag "shadowless1-core:$1" shadowless1-core:current
  install -m 644 deploy/shadowless1-core.service /etc/systemd/system/shadowless1-core.service
  systemctl daemon-reload
  systemctl enable --quiet shadowless1-core
  systemctl restart shadowless1-core
}

healthy() {
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 http://127.0.0.1:8000/healthz >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

echo "== starting"
switch_to "$sha"
if ! healthy; then
  echo "new version is not healthy; last log lines (masked):" >&2
  journalctl -u shadowless1-core -n 30 --no-pager -o cat 2>/dev/null | mask >&2 || true
  if [[ $prev != none ]] && docker image inspect "shadowless1-core:$prev" >/dev/null 2>&1; then
    echo "switching back to $prev" >&2
    switch_to "$prev"
    healthy && echo "previous version $prev is running again" >&2
  fi
  exit 1
fi

echo "== proxy"
site=$(cat /etc/shadowless1/site)
sed "s|__SITE__|$site|" deploy/Caddyfile > /etc/caddy/Caddyfile.new
caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile >/dev/null 2>&1
mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile
systemctl reload caddy

echo "$sha" > "$state/current"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $sha previous=$prev" >> "$state/deploy.log"

# Keep the images of the current and the previous deploy (for a quick rollback); remove older ones.
docker images shadowless1-core --format '{{.Tag}}' | grep -vxE "current|$sha|$prev" \
  | xargs -r -I{} docker rmi -f "shadowless1-core:{}" >/dev/null 2>&1 || true

echo "deployed $sha; local /healthz: $(curl -fsS --max-time 2 http://127.0.0.1:8000/healthz)"
