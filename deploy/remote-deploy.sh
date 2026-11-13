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

# Log mask for failure output. It errs on the side of hiding:
# - a credential-looking key (also inside names such as GEMINI_API_KEY or DB_PASSWORD) followed by
#   ':' or '=' hides everything to the end of the line, quotes and spaces included;
# - a URL hides everything after its scheme to the end of the line;
# - a line with something@host.domain (credentials at a host) is hidden as a whole;
# - 'Bearer <token>', the word after 'host', 'host name' or 'server at' (quoted or not), user names
#   ('user=…', 'for user "…"'), host-like names with a common top-level domain, IPv4 and IPv6
#   addresses are replaced. 127.0.0.1 and 0.0.0.0 stay readable ("listening on" lines).
mask() {
  sed -E \
    -e 's#.*[^[:space:]]@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+.*#*** (line hidden: credentials at a host)#' \
    -e 's#([A-Za-z][A-Za-z0-9+.-]*://).*#\1***#' \
    -e 's#(^|[^A-Za-z0-9])([A-Za-z0-9_]*(password|passwd|pwd|secret|token|api[_-]?key|key|authorization|credentials?|cookie|dsn|database_url))(["'"'"']?[[:space:]]*[:=]).*#\1\2\4 ***#I' \
    -e 's#(bearer)[[:space:]]+[^[:space:]]+#\1 ***#Ig' \
    -e 's#(host name|hostname|server at|\bhost)([[:space:]]*[:=]?[[:space:]]*["'"'"']?)[A-Za-z0-9._-]+#\1\2***#Ig' \
    -e 's#\b(user|username)([[:space:]]*=[[:space:]]*["'"'"']?)[^"'"'"'[:space:]]+#\1\2***#Ig' \
    -e 's#(for user[[:space:]]+["'"'"']?)[^"'"'"'[:space:]]+#\1***#Ig' \
    -e 's#\b[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.(com|net|org|io|dev|cloud|fi|eu|co|ai|tech|xyz|info)\b#***#Ig' \
    -e 's#\b127\.0\.0\.1\b#__LOOPBACK4__#g; s#\b0\.0\.0\.0\b#__ANY4__#g' \
    -e 's#\b([0-9]{1,3}\.){3}[0-9]{1,3}\b#x.x.x.x#g' \
    -e 's#__LOOPBACK4__#127.0.0.1#g; s#__ANY4__#0.0.0.0#g' \
    -e 's#\b([0-9A-Fa-f]{1,4}:){5,7}[0-9A-Fa-f]{1,4}\b#x:x::x#g' \
    -e 's#([0-9A-Fa-f]{1,4}:){1,6}:([0-9A-Fa-f]{1,4}(:[0-9A-Fa-f]{1,4}){0,5})?#x:x::x#g' \
    -e 's#(^|[^0-9A-Za-z]):(:[0-9A-Fa-f]{1,4}){1,7}#\1x:x::x#g'
}

# Self-test: each sample is masked and must not contain any of its secrets afterwards; the plain
# log line must stay unchanged. Exits 1 if anything leaks.
if [[ ${1:-} == --self-test-mask ]]; then
  failed=0
  while IFS=$'\t' read -r sample secrets; do
    [[ -z $sample ]] && continue
    out=$(printf '%s\n' "$sample" | mask)
    leak=""
    IFS=';' read -ra parts <<<"$secrets"
    for s in "${parts[@]}"; do
      [[ $s == "=UNCHANGED" ]] && { [[ $out == "$sample" ]] || leak="(changed)"; continue; }
      [[ -n $s && $out == *"$s"* ]] && leak+=" [$s]"
    done
    if [[ -n $leak ]]; then
      echo "LEAK $out   <- still contains:$leak"; failed=1
    else
      echo "ok   $out"
    fi
  done <<'EOF'
postgresql://u:p@ss@db.example.com/x?sslmode=require	p@ss;db.example.com
error: postgresql://u:p/ss@db.example.com:5432/x failed	p/ss;db.example.com
connection to server at "db.example.com" (203.0.113.7), port 5432 failed	db.example.com;203.0.113.7
host=db.example.com user=app password=s3cret dbname=core	db.example.com;s3cret;user=app
host='db.example.com' port=5432	db.example.com
FATAL:  password authentication failed for user "app_user"	app_user
connection failed: user = 'app_user'	app_user
INFO:     Uvicorn listening on 0.0.0.0:8000 and 127.0.0.1:8000	=UNCHANGED
GEMINI_API_KEY=AIzaSyFAKE0000	AIzaSyFAKE0000
MY_SERVICE_TOKEN=tok_abc123	tok_abc123
APP_SECRET=sh_secret_9	sh_secret_9
password = "s3cret"	s3cret
PASSWORD:s3cret	s3cret
api_key: "abc123key"	abc123key
Authorization: Bearer eyJhbGciOiFAKE	eyJhbGciOiFAKE
password='s3 cret'	s3;cret
u:"pa ss word"@db.example.com	pa ss;word;db.example.com
could not translate host name db.example.com to address	db.example.com
db.example.com	db.example.com
connection to 2001:db8::17 refused	2001:db8::17
listening on ::1 and fe80::1ff:fe23:4567:890a	::1;fe80::1ff:fe23:4567:890a
GET /healthz?token=abc HTTP/1.1 from 198.51.100.4:51234	token=abc;198.51.100.4
INFO:     Application startup complete.	=UNCHANGED
shadowless1-core.service: Main process exited, code=exited, status=1/FAILURE	=UNCHANGED
EOF
  if (( failed )); then echo "mask self-test FAILED"; exit 1; fi
  echo "mask self-test passed"
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

# A build refused before the switch is removed again (never the image of the running commit).
drop_image() {
  [[ $sha == "$prev" ]] || docker rmi "shadowless1-core:$sha" >/dev/null 2>&1 || true
}

echo "== image contents (must not hold .env, .git or tests)"
listing=$(docker run --rm --entrypoint sh "shadowless1-core:$sha" -c 'cd /srv && find . -not -path "*/__pycache__*" | sort')
echo "$listing" | grep -vE '^\./core/(metrics|tools)/.+\.(sql|py)$' | tr '\n' ' '
echo "(+ $(grep -cE '^\./core/tools/.+\.py$' <<<"$listing") files in core/tools, $(grep -cE '^\./core/metrics/.+\.sql$' <<<"$listing") in core/metrics)"
if grep -qE '(^|/)(\.env|\.git|tests)(/|$)' <<<"$listing"; then
  echo "refusing to deploy: the image contains .env, .git or tests" >&2
  drop_image
  exit 1
fi

# Completeness check, before the switch. The expectation comes from the checkout, not from the
# image: every tracked file the service imports or reads at run time must be in the image. A path
# left out of /.dockerignore fails here, the running version stays untouched. A new kind of run-time
# file (for example core/data/*.csv) must be added to these patterns as well as to /.dockerignore.
# The list is built in the main shell, so a git failure stops the deploy instead of passing an empty
# list; a list without core/app/main.py is refused too.
if ! expected=$(git ls-files -- 'core/app/*.py' 'core/tools/*.py' 'core/agent/*.py' \
                  'core/metrics/*.sql' 'core/config/*.yaml'); then
  echo "refusing to deploy: cannot list the run-time files of the checkout" >&2
  drop_image
  exit 1
fi
expected=$(grep -vE '(^|/)tests/' <<<"$expected" || true)
if ! grep -qxF core/app/main.py <<<"$expected"; then
  echo "refusing to deploy: the list of run-time files from git is empty or lacks core/app/main.py" >&2
  drop_image
  exit 1
fi
missing=()
while IFS= read -r f; do
  grep -qxF "./$f" <<<"$listing" || missing+=("$f")
done <<<"$expected"
if (( ${#missing[@]} )); then
  echo "refusing to deploy: ${#missing[@]} file(s) the service needs are not in the image (see /.dockerignore):" >&2
  printf '  %s\n' "${missing[@]:0:10}" >&2
  drop_image
  exit 1
fi
echo "all run-time files of the checkout are in the image"

# Import check, before the switch: the image must be able to import and build the application and
# every module of the tools and the answer pipeline. An import error fails here as well.
echo "== import check"
import_check='
import importlib, importlib.util, pkgutil
import core.app.main as m
m.create_app()
n = 1
for pkg in ("core.tools", "core.agent"):
    if importlib.util.find_spec(pkg) is None:
        continue  # no such package in this commit (the completeness check covers a left-out one)
    for info in pkgutil.walk_packages(importlib.import_module(pkg).__path__, pkg + "."):
        if ".tests" not in info.name:
            importlib.import_module(info.name)
            n += 1
print(f"imports ok: core.app and {n - 1} modules of core.tools/core.agent")
'
if ! import_out=$(docker run --rm --network none --entrypoint python "shadowless1-core:$sha" -c "$import_check" 2>&1); then
  echo "refusing to deploy: the image cannot import the application; last lines (masked):" >&2
  tail -8 <<<"$import_out" | mask >&2
  drop_image
  exit 1
fi
tail -1 <<<"$import_out" | mask

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
