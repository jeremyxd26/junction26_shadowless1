"""Scan the lines a branch adds for secrets (issue #472): a local check for when the CI secret scan
cannot run, and a quick one before any merge.

Run from the repository root (fetch first):
    python scripts/scan_diff_secrets.py --base origin/dev                  # HEAD against origin/dev
    python scripts/scan_diff_secrets.py --base origin/dev --head my-branch
    python scripts/scan_diff_secrets.py --pr 443                           # refs/pull/443/head vs origin/dev
    python scripts/scan_diff_secrets.py --range 0af28d1..9e2f4bb           # what a range of commits added
PR heads need `git fetch origin "+refs/pull/*/head:refs/pull/*/head"`.

Only lines added between the merge base and the head are read. It reports:
- common key shapes (Google, GitHub, OpenAI or Anthropic, AWS, private key blocks, Slack, JWT, and
  `secret = "..."`-style assignments);
- postgres URLs with a password, unless the `postgres-url-password` allowlist of `.gitleaks.toml`
  covers it (path AND value, as gitleaks applies that allowlist);
- literal values of the local `.env` of 12 or more characters (skipped, with a note, without one);
- added `.env` files (`.env.example` is fine).
Output names the kind and the file only, never a value. Exit code 1 on a finding, 0 when clean, 2 when
the scan cannot run (an unknown ref, for example).

It does not replace gitleaks: gitleaks has many more rules and, in CI, reads the whole history of every
branch; `scripts/scan_env_values.py` covers the history, pull request heads and GitHub texts.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

KEY_SHAPES = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "github_token": re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{30,}"),
    "openai_or_anthropic_key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}"),
    "aws_key_id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    "slack_token": re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{10,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "secret_assignment": re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
}
POSTGRES_URL = re.compile(r"""postgres(?:ql)?://[^:/@\s"'`]+:(?P<pw>[^@\s"'`]+)@""")
ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]*)?$")
MIN_ENV_LEN = 12


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str

    def __str__(self) -> str:
        return f"{self.kind} in {self.path}"


@dataclass(frozen=True)
class Allowlist:
    """One `[[rules.allowlists]]` entry of the postgres rule: a password is allowed when the file path
    matches one of `paths` and the password matches one of `regexes` (condition AND)."""
    paths: tuple[re.Pattern, ...]
    regexes: tuple[re.Pattern, ...]

    def allows(self, path: str, password: str) -> bool:
        if not self.paths and not self.regexes:
            return False
        path_ok = not self.paths or any(p.search(path) for p in self.paths)
        value_ok = not self.regexes or any(r.search(password) for r in self.regexes)
        return path_ok and value_ok


def load_allowlists(config: Path) -> list[Allowlist]:
    """The allowlists of the `postgres-url-password` rule; none without the file or the rule."""
    if not config.exists():
        return []
    rules = tomllib.loads(config.read_text(encoding="utf-8")).get("rules", [])
    rule = next((r for r in rules if r.get("id") == "postgres-url-password"), None)
    if rule is None:
        return []
    out = []
    for entry in rule.get("allowlists", []) or ([rule["allowlist"]] if "allowlist" in rule else []):
        out.append(Allowlist(tuple(re.compile(p) for p in entry.get("paths", [])),
                             tuple(re.compile(r) for r in entry.get("regexes", []))))
    return out


def load_env_values(env: Path) -> dict[str, str]:
    """Name -> value for every value of MIN_ENV_LEN or more characters; empty without the file."""
    if not env.exists():
        return {}
    values = {}
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if len(value) >= MIN_ENV_LEN:
            values[name.strip()] = value
    return values


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def added_lines(repo: Path, base: str, head: str) -> tuple[set[str], list[tuple[str, str]]]:
    """(changed files, [(file, added line)]) of `head` against its merge base with `base`."""
    since = git(repo, "merge-base", base, head).strip()
    return diff_added(git(repo, "diff", "--no-color", "-U0", since, head))


def diff_added(diff: str) -> tuple[set[str], list[tuple[str, str]]]:
    files: set[str] = set()
    added: list[tuple[str, str]] = []
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
            if path != "/dev/null":
                files.add(path)
        elif line.startswith("+") and not line.startswith("+++"):
            added.append((path, line[1:]))
    return files, added


def scan(files: set[str], added: list[tuple[str, str]], env_values: dict[str, str],
         allowlists: list[Allowlist]) -> list[Finding]:
    found: list[Finding] = []
    for path, text in added:
        for kind, rx in KEY_SHAPES.items():
            if rx.search(text):
                found.append(Finding(kind, path))
        for m in POSTGRES_URL.finditer(text):
            if not any(a.allows(path, m.group("pw")) for a in allowlists):
                found.append(Finding("postgres_url_with_password", path))
        for name, value in env_values.items():
            if value in text:
                found.append(Finding(f"env_value:{name}", path))
    for path in sorted(files):
        if ENV_FILE.search(path) and not path.endswith(".env.example"):
            found.append(Finding("env_file", path))
    return sorted(set(found), key=lambda f: (f.path, f.kind))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--pr", type=int, help="scan refs/pull/<N>/head against --base")
    target.add_argument("--range", help="scan what A..B added")
    parser.add_argument("--base", default="origin/dev", help="the branch the head will merge into")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--gitleaks-config", default=".gitleaks.toml")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    try:
        if args.range:
            if ".." not in args.range:
                print("--range needs A..B")
                return 2
            base, head = args.range.split("..", 1)
            files, added = diff_added(git(repo, "diff", "--no-color", "-U0", base, head))
            label = f"range {git(repo, 'rev-parse', '--short', base).strip()}..{git(repo, 'rev-parse', '--short', head).strip()}"
        else:
            head = f"refs/pull/{args.pr}/head" if args.pr else args.head
            files, added = added_lines(repo, args.base, head)
            label = f"{'#' + str(args.pr) if args.pr else head} at {git(repo, 'rev-parse', '--short', head).strip()} vs {args.base}"
    except subprocess.CalledProcessError as exc:
        print(f"NOT RUN: git failed ({' '.join(exc.cmd[3:5])}); is the ref fetched?")
        return 2

    env_values = load_env_values(repo / args.env)
    allowlists = load_allowlists(repo / args.gitleaks_config)
    found = scan(files, added, env_values, allowlists)
    note = "" if env_values else " (no .env values loaded: the literal check was skipped)"
    print(f"{label}: {len(files)} files, {len(added)} added lines; findings: {len(found)}{note}")
    for f in found:
        print(f"  {f}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
