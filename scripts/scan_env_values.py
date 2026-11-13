"""Look for the values of the local .env anywhere in the repository and its GitHub texts (issue #82).

Run from the repository root of the main checkout (the one with the real .env):
    python scripts/scan_env_values.py            # fetch, then git history, ref names and GitHub texts
    python scripts/scan_env_values.py --no-api   # git only
    python scripts/scan_env_values.py --no-fetch # use the refs that are already local

It prints variable NAMES and hit counts only, never a value. Every value of 12 or more characters
is searched as a literal, and for a URL value with a password of 8 or more characters the password
alone as well ("NAME (password)"). First it fetches every branch, tag and pull request head
(`refs/pull/*/head`, which become public with the repository). Then it searches:
- `git log --all -p --diff-merges=first-parent`: every commit reachable from any local or remote
  branch, tag or pull request head, with commit messages and what each merge changed (gitleaks does
  not show merge diffs);
- branch, tag and pull request ref names;
- through the GitHub API (needs `gh`): issue and pull request titles and bodies, issue and pull
  request comments, review comments, review summaries, and the earlier versions of every edited
  issue or pull request body and comment (GraphQL `userContentEdits`).
A second check runs on the GitHub texts: shapes of common keys (Google API key, GitHub token,
OpenAI or Anthropic key, AWS key id, private key block, postgres URL with a password), place and shape
name only. The git history gets those shapes from gitleaks (.gitleaks.toml, CI job "Secret scan").
Exit code: 1 if anything is found, 2 if the check could not run completely (no .env value loaded),
0 when clean.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

MIN_LEN = 12
MIN_PASSWORD_LEN = 8
KEY_SHAPES = {
    "google_api_key": r"AIza[0-9A-Za-z_\-]{35}",
    "github_token": r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{30,}",
    "openai_or_anthropic_key": r"\bsk-(ant-)?[A-Za-z0-9_\-]{20,}",
    "aws_key_id": r"\bAKIA[0-9A-Z]{16}\b",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY",
    "postgres_url_with_password": r"postgres(?:ql)?://[^:/@\s\"'`]+:(?P<pw>[^@\s\"'`]{6,})@",
}
FETCH_REFSPECS = ("+refs/heads/*:refs/remotes/origin/*", "+refs/tags/*:refs/tags/*",
                  "+refs/pull/*/head:refs/pull/*/head")


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
    """Name -> value for every value of MIN_LEN+ characters, plus the password of a URL value."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if len(value) >= MIN_LEN:
            values[name] = value
        try:
            password = urlsplit(value).password if "://" in value else None
        except ValueError:
            password = None
        if password and len(password) >= MIN_PASSWORD_LEN:
            values[f"{name} (password)"] = password
            if unquote(password) != password:
                values[f"{name} (password, decoded)"] = unquote(password)
    return values


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def paged(endpoint: str) -> list[dict]:
    out = gh("api", "--paginate", endpoint).strip()
    # --paginate concatenates the JSON arrays of the pages: "][" between pages
    return json.loads("[" + out[1:-1].replace("][", ",") + "]") if out not in ("", "[]") else []


EDITS_QUERY = """
query($owner: String!, $name: String!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    %s(first: 25, after: $endCursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        userContentEdits(first: 50) { nodes { diff } }
        comments(first: 50) { nodes { userContentEdits(first: 20) { nodes { diff } } } }
        %s
      }
    }
  }
}"""
REVIEW_EDITS = "reviews(first: 50) { nodes { userContentEdits(first: 20) { nodes { diff } } } }"


def edit_versions(repo: str) -> list[tuple[str, str]]:
    """Earlier versions of edited issue and PR bodies, their comments and PR review summaries."""
    owner, name = repo.split("/")
    texts = []
    for kind, extra in (("issues", ""), ("pullRequests", REVIEW_EDITS)):
        cursor = None
        while True:
            args = ["api", "graphql", "-f", f"query={EDITS_QUERY % (kind, extra)}", "-F", f"owner={owner}",
                    "-F", f"name={name}"]
            if cursor:
                args += ["-F", f"endCursor={cursor}"]
            page = json.loads(gh(*args))["data"]["repository"][kind]
            for node in page["nodes"]:
                where = f"{'pr' if kind == 'pullRequests' else 'issue'} #{node['number']}"
                texts += [(f"{where} body, earlier version", e["diff"] or "") for e in node["userContentEdits"]["nodes"]]
                for c in node["comments"]["nodes"]:
                    texts += [(f"{where} comment, earlier version", e["diff"] or "") for e in c["userContentEdits"]["nodes"]]
                for r in (node.get("reviews") or {}).get("nodes", []):
                    texts += [(f"{where} review, earlier version", e["diff"] or "") for e in r["userContentEdits"]["nodes"]]
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
    return texts


def gh_texts(repo: str) -> list[tuple[str, str]]:
    """(place, text) for every GitHub text this check covers."""
    texts = []
    prs = []
    for item in paged(f"repos/{repo}/issues?state=all&per_page=100"):  # issues and PRs
        kind = "pr" if "pull_request" in item else "issue"
        if kind == "pr":
            prs.append(item["number"])
        texts.append((f"{kind} #{item['number']} title", item.get("title") or ""))
        texts.append((f"{kind} #{item['number']} body", item.get("body") or ""))
    for c in paged(f"repos/{repo}/issues/comments?per_page=100"):
        texts.append((f"comment on #{c['issue_url'].rsplit('/', 1)[-1]} ({c['id']})", c.get("body") or ""))
    for c in paged(f"repos/{repo}/pulls/comments?per_page=100"):
        texts.append((f"review comment on PR #{c['pull_request_url'].rsplit('/', 1)[-1]} ({c['id']})", c.get("body") or ""))
    for n in prs:
        for r in paged(f"repos/{repo}/pulls/{n}/reviews?per_page=100"):
            texts.append((f"review summary on PR #{n} ({r['id']})", r.get("body") or ""))
    texts += edit_versions(repo)
    return texts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", default=".env")
    parser.add_argument("--no-api", action="store_true", help="skip the GitHub texts")
    parser.add_argument("--no-fetch", action="store_true", help="do not fetch; scan the local refs as they are")
    parser.add_argument("--gitleaks-config", default=".gitleaks.toml",
                        help="where the synthetic test passwords are allowlisted")
    args = parser.parse_args()

    env = Path(args.env)
    values = env_values(env) if env.exists() else {}
    print(f"{len(values)} values to look for from {args.env} ({MIN_LEN}+ characters, and URL passwords)")
    if not values:
        print("RESULT: NOT RUN - no value loaded; run it where the real .env is")
        return 2

    if not args.no_fetch:
        git("fetch", "--prune", "--quiet", "origin", *FETCH_REFSPECS)
    history = git("log", "--all", "-p", "--diff-merges=first-parent", "--no-color")
    refs = git("for-each-ref", "--format=%(refname)")
    n_pull = sum(1 for r in refs.split() if r.startswith("refs/pull/"))
    print(f"git: {len(git('rev-list', '--all').split())} commits, {len(refs.split())} refs "
          f"({n_pull} pull request heads)")
    if n_pull == 0:
        print("  warning: no refs/pull/*/head; pull request heads are not covered (run without --no-fetch)")

    texts: list[tuple[str, str]] = []
    if not args.no_api:
        repo = gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()
        texts = gh_texts(repo)
        print(f"github: {len(texts)} texts (titles, bodies, comments, reviews, earlier versions)")

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
