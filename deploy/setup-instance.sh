#!/usr/bin/env bash
# One-time setup of the dev instance (Ubuntu 24.04), run as root on the instance:
#   git show HEAD:deploy/setup-instance.sh | ssh -i ~/.ssh/shadowless1_dev_ed25519 root@<ip> 'bash -s -- <ip>'
# Installs Docker, Caddy, ufw and git; opens only ports 22, 80 and 443; turns off SSH password login;
# creates a read-only GitHub deploy key on the instance (the private key never leaves it) and prints
# its public half; prepares /etc/shadowless1 (root only) for the service settings.
# Safe to re-run. Prints no secret.
set -euo pipefail

ip=${1:?usage: setup-instance.sh <public-ip>}
[[ $ip =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "not an IPv4 address: $ip" >&2; exit 1; }
repo_url=git@github.com:jeremyxd26/junction26_shadowless1.git
# GitHub's published SSH host key fingerprint (https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)
github_ed25519=SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU

echo "== waiting for cloud-init"
cloud-init status --wait >/dev/null 2>&1 || true

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io caddy ufw git curl ca-certificates >/dev/null
systemctl enable --now docker >/dev/null

echo "== firewall: only 22, 80, 443"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status | sed -n '1,12p'

echo "== ssh: keys only"
# sshd uses the first value it reads, so this file must sort before cloud-init's 50-cloud-init.conf.
cat > /etc/ssh/sshd_config.d/00-shadowless1.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
sshd -t
systemctl reload ssh
sshd -T | grep -E '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin) '

echo "== settings directory (root only)"
install -d -m 700 /etc/shadowless1
if [[ ! -f /etc/shadowless1/core.env ]]; then
  install -m 600 /dev/null /etc/shadowless1/core.env
  printf 'DEMO_TODAY=2026-09-30\n' > /etc/shadowless1/core.env
fi
chmod 600 /etc/shadowless1/core.env
site_file=/etc/shadowless1/site
[[ -f $site_file ]] || echo "${ip//./-}.sslip.io" > "$site_file"
echo "site: $(cat "$site_file")"

echo "== GitHub deploy key (read-only)"
install -d -m 700 /root/.ssh
if [[ ! -f /root/.ssh/github_deploy ]]; then
  ssh-keygen -q -t ed25519 -N "" -C "shadowless1-dev-instance" -f /root/.ssh/github_deploy
fi
scanned=$(ssh-keyscan -t ed25519 github.com 2>/dev/null)
fingerprint=$(ssh-keygen -lf - <<<"$scanned" | awk '{print $2}')
[[ $fingerprint == "$github_ed25519" ]] || { echo "github.com host key mismatch: $fingerprint" >&2; exit 1; }
grep -qF "$scanned" /root/.ssh/known_hosts 2>/dev/null || echo "$scanned" >> /root/.ssh/known_hosts
cat > /root/.ssh/config <<'EOF'
Host github.com
  IdentityFile /root/.ssh/github_deploy
  IdentitiesOnly yes
EOF
chmod 600 /root/.ssh/config
echo "add this public key to the repository as a read-only deploy key:"
cat /root/.ssh/github_deploy.pub

install -d -m 755 /opt/shadowless1
if [[ -d /opt/shadowless1/repo/.git ]]; then
  echo "== repository already cloned"
elif git ls-remote --heads "$repo_url" >/dev/null 2>&1; then
  echo "== cloning"
  git clone --quiet "$repo_url" /opt/shadowless1/repo
else
  echo "== not cloned yet: add the deploy key above, then re-run this script"
fi
echo "setup done"
