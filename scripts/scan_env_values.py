"""Look for the values of the local .env anywhere in the repository and its GitHub texts (issue #82).

Run from the repository root, after `git fetch --all --tags`:
    python scripts/scan_env_values.py            # git history of every ref, ref names, GitHub texts
    python scripts/scan_env_values.py --no-api   # git only

It prints variable NAMES and hit counts only, never a value. Every value of 12 or more characters
is searched as a literal:
- in `git log --all -p --diff-merges=first-parent` (every commit reachable from any branch, remote
  branch or tag, with commit messages, and what each merge changed, which gitleaks does not show);
- in branch and tag names;
- through the GitHub API (needs `gh`): issue and pull request titles, bodies and comments, and
  review comments.
A second check runs on the GitHub texts only: shapes of common keys (Google API key, GitHub token,
OpenAI or Anthropic key, AWS key id, private key block, postgres URL with a password). It prints the
place and the shape name. The git history gets the same shapes from gitleaks (.gitleaks.toml).
Exit code 1 if anything is found, else 0.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

MIN_LEN = 12
KEY_SHAPES = {
    "google_api_key": r"AIza[0-9A-Za-z_\-]{35}",
    "github_token": r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{30,}",
    "openai_or_anthropic_key": r"\bsk-(ant-)?[A-Za-z0-9_\-]{20,}",
    "aws_key_id": r"\bAKIA[0-9A-Z]{16}\b",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY",
    "postgres_url_with_password": r"postgres(?:ql)?://[^:/@\s\"'`]+:(?P<pw>[^@\s\"'`]{6,})@",
}


def synthetic_passwords(config_path: str = ".gitleaks.toml") -> re.Pattern:
    """The synthetic test passwords allowlisted for the postgres rule in .gitleaks.toml (one list).
    Without that file nothing is allowlisted and every postgres URL with a password is reported."""
    path = Path(config_path)
    if not path.exists():
        return re.compile(r"(?!)")
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    rule = next(r for r in config["rules"] if r["id"] == "postgres-url-password")
    return re.compile("|".join(f"(?:{rx})" for a in rule["allowlists"] for rx in a["regexes"]))


def env_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if len(value) >= MIN_LEN:
            values[name.strip()] = value
    return values


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def gh_texts(repo: str) -> list[tuple[str, str]]:
    """(place, text) for every issue and PR title, body and comment, and every review comment."""
    def paged(endpoint: str) -> list[dict]:
        out = subprocess.run(["gh", "api", "--paginate", endpoint], capture_output=True, text=True,
                             encoding="utf-8", check=True).stdout
        # --paginate concatenates JSON arrays: "][" between pages
        return json.loads("[" + out.strip()[1:-1].replace("][", ",") + "]") if out.strip() not in ("", "[]") else []

    texts = []
    for item in paged(f"repos/{repo}/issues?state=all&per_page=100"):  # issues and PRs
        kind = "pr" if "pull_request" in item else "issue"
        texts.append((f"{kind} #{item['number']} title", item.get("title") or ""))
        texts.append((f"{kind} #{item['number']} body", item.get("body") or ""))
    for c in paged(f"repos/{repo}/issues/comments?per_page=100"):
        texts.append((f"comment on #{c['issue_url'].rsplit('/', 1)[-1]} ({c['id']})", c.get("body") or ""))
    for c in paged(f"repos/{repo}/pulls/comments?per_page=100"):
        texts.append((f"review comment on PR #{c['pull_request_url'].rsplit('/', 1)[-1]} ({c['id']})", c.get("body") or ""))
    return texts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", default=".env")
    parser.add_argument("--no-api", action="store_true", help="skip the GitHub texts")
    parser.add_argument("--gitleaks-config", default=".gitleaks.toml",
                        help="where the synthetic test passwords are allowlisted")
    args = parser.parse_args()

    values = env_values(Path(args.env))
    print(f"{len(values)} values of {MIN_LEN}+ characters in {args.env}")
    history = git("log", "--all", "-p", "--diff-merges=first-parent", "--no-color")
    refs = git("for-each-ref", "--format=%(refname)")
    print(f"git: {len(git('rev-list', '--all').split())} commits, {len(refs.split())} refs")

    texts: list[tuple[str, str]] = []
    if not args.no_api:
        repo = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
                              capture_output=True, text=True, check=True).stdout.strip()
        texts = gh_texts(repo)
        print(f"github: {len(texts)} texts (titles, bodies, comments)")

    found = 0
    print("\nvariable: hits in history / ref names / GitHub texts")
    for name, value in sorted(values.items()):
        h, r = history.count(value), refs.count(value)
        t = sum(text.count(value) for _, text in texts)
        found += h + r + t
        print(f"  {name}: {h} / {r} / {t}")

    synthetic = synthetic_passwords(args.gitleaks_config)
    shape_hits = 0
    for place, text in texts:
        for shape, rx in KEY_SHAPES.items():
            for m in re.finditer(rx, text):
                pw = m.group("pw") if "pw" in rx else None
                if pw is not None and synthetic.match(pw):
                    print(f"  synthetic test value (allowlisted in .gitleaks.toml): {shape} in {place}")
                    continue
                shape_hits += 1
                print(f"  key shape {shape} in {place}")
    print(f"\nkey shapes in GitHub texts: {shape_hits}")
    print("RESULT:", "FOUND - treat the variable as leaked and tell the team lead" if found or shape_hits else "clean")
    return 1 if found or shape_hits else 0


if __name__ == "__main__":
    sys.exit(main())
