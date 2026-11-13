#!/usr/bin/env bash
# Runs ON the dev instance as root, from /opt/shadowless1/repo already checked out at <sha>.
# Called by deploy/dev.sh; not meant to be run by hand except for debugging.
# Builds the image for <sha>, switches the service to it, waits for /healthz, renders the Caddy config.
# If the new version does not start or does not become healthy, it switches back to the previous
# commit's image AND that commit's unit file. Never prints the settings file or environment values;
# failure logs are masked.
#
#   remote-deploy.sh <commit-sha> [health-path]
#   remote-deploy.sh --self-test-mask        # print sample lines through the log mask and exit
set -euo pipefail

# Log mask for failure output: everything after a URL scheme up to the next space, key=value pairs
# that name connection details or secrets, quoted host names and IPv4 addresses.
mask() {
  sed -E \
    -e 's#([A-Za-z][A-Za-z0-9+.-]*://)[^[:space:]]*#\1***#g' \
    -e 's#\b(host|hostaddr|user|dbname|password|passfile|sslpassword|secret|key|token)=[^[:space:]&]*#\1=***#Ig' \
    -e 's#"[^"[:space:]]*\.[A-Za-z]{2,}"#"***"#g' \
    -e 's#\b([0-9]{1,3}\.){3}[0-9]{1,3}\b#x.x.x.x#g'
}

if [[ ${1:-} == --self-test-mask ]]; then
  mask <<'EOF'
postgresql://u:p@ss@db.example.com/x?sslmode=require
error: postgresql://u:p/ss@db.example.com:5432/x failed
connection to server at "db.example.com" (203.0.113.7), port 5432 failed
host=db.example.com user=app password=s3cret dbname=core
GET /healthz?token=abc HTTP/1.1 from 198.51.100.4:51234
INFO:     Application startup complete.
EOF
  exit 0
fi

sha=${1:?usage: remote-deploy.sh <commit-sha> [health-path]}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "not a full commit sha: $sha" >&2; exit 1; }
# The deploy gate. Only for testing the rollback path is it set to a path that does not exist.
health_path=${2:-/healthz}
[[ $health_path =~ ^/[A-Za-z0-9._/-]*$ ]] || { echo "unsupported health path: $health_path" >&2; exit 1; }
cd /opt/shadowless1/repo
state=/opt/shadowless1
prev=$(cat "$state/current" 2>/dev/null || echo none)

echo "== building $sha (previous: $prev)"
docker build --quiet --file deploy/Dockerfile --tag "shadowless1-core:$sha" . >/dev/null

echo "== image contents (must not hold .env, .git or tests)"
listing=$(docker run --rm --entrypoint sh "shadowless1-core:$sha" -c 'cd /srv && find . -maxdepth 3 -not -path "*/__pycache__*" | sort')
echo "$listing" | tr '\n' ' '; echo
if grep -qE '(^|/)(\.env|\.git|tests)(/|$)' <<<"$listing"; then
  echo "refusing to deploy: the image contains .env, .git or tests" >&2
  exit 1
fi

# Switch the service to commit $1: its image and ITS unit file (from git, so a rollback never uses the
# failed commit's unit). Every step returns its own error: `set -e` does not apply inside an `if`.
switch_to() {
  local unit=/etc/systemd/system/shadowless1-core.service
  docker tag "shadowless1-core:$1" shadowless1-core:current || return 1
  git show "$1:deploy/shadowless1-core.service" > "$unit.new" || return 1
  install -m 644 "$unit.new" "$unit" && rm -f "$unit.new" || return 1
  systemctl daemon-reload || return 1
  systemctl enable --quiet shadowless1-core || return 1
  systemctl restart shadowless1-core || return 1
}

healthy() {   # $1: path to check (default /healthz)
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 "http://127.0.0.1:8000${1:-/healthz}" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

echo "== starting"
if ! switch_to "$sha" || ! healthy "$health_path"; then
  echo "new version did not start or is not healthy (GET $health_path); last log lines (masked):" >&2
  journalctl -u shadowless1-core -n 30 --no-pager -o cat 2>/dev/null | mask >&2 || true
  if [[ $prev != none ]] && docker image inspect "shadowless1-core:$prev" >/dev/null 2>&1; then
    echo "switching back to $prev (its image and its unit file)" >&2
    if switch_to "$prev" && healthy; then
      echo "previous version $prev is running again" >&2
    else
      echo "previous version $prev did not start either; the service is down" >&2
    fi
  else
    echo "no previous version to switch back to; the service is down" >&2
  fi
  exit 1
fi

# The new version is live: record it before anything else can fail, so the next deploy's
# "previous" is right.
echo "$sha" > "$state/current"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $sha previous=$prev" >> "$state/deploy.log"

echo "== proxy"
site=$(cat /etc/shadowless1/site)
sed "s|__SITE__|$site|" deploy/Caddyfile > /etc/caddy/Caddyfile.new
if ! caddy_error=$(caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile 2>&1); then
  echo "proxy config is invalid; $sha is running but the proxy still uses its previous config:" >&2
  tail -5 <<<"$caddy_error" | mask >&2
  rm -f /etc/caddy/Caddyfile.new
  exit 1
fi
mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile
systemctl reload caddy

# Keep the images of the current and the previous deploy (for a quick rollback); remove older ones.
docker images shadowless1-core --format '{{.Tag}}' | grep -vxE "current|$sha|$prev" \
  | xargs -r -I{} docker rmi -f "shadowless1-core:{}" >/dev/null 2>&1 || true

echo "deployed $sha; local /healthz: $(curl -fsS --max-time 2 http://127.0.0.1:8000/healthz)"
