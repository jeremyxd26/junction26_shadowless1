"""Scan the lines a branch adds for secrets (issue #472): a local check for when the CI secret scan
cannot run, and a quick one before any merge.

Run from the repository root (fetch first):
    python scripts/scan_diff_secrets.py --base origin/dev                  # HEAD against origin/dev
    python scripts/scan_diff_secrets.py --base origin/dev --head my-branch
    python scripts/scan_diff_secrets.py --pr 443                           # refs/pull/443/head vs origin/dev
    python scripts/scan_diff_secrets.py --range 0af28d1..9e2f4bb           # what a range of commits added
PR heads need `git fetch origin "+refs/pull/*/head:refs/pull/*/head"`; a missing ref is named, with the
command that fetches it.

What is read. By default every commit between the merge base and the head, and the final diff as well:
a secret added in one commit and removed in a later one stays in the history that a merge commit brings
into dev and main. A merge commit is read as its remerge diff (git 2.36 or newer): the lines written
while resolving it. What a merge brings from its parents is read in their own commits, or is already in
the base. `--net-only` reads the final diff alone. Only added lines count. Files are read as text, binary
ones included; a file git still reports as binary is listed (path only) as skipped.

What it reports:
- common key shapes (Google, GitHub, OpenAI or Anthropic, AWS, NVIDIA, private key blocks, Slack, JWT), and
  values assigned to a key, secret, password or token name, quoted (`token = "..."`) or not
  (`export API_TOKEN=...`, `password: ...`);
- postgres URLs with a password, unless the `postgres-url-password` allowlist of `.gitleaks.toml`
  covers it (path AND value, as gitleaks applies that allowlist). The allowlist is read from the base's
  copy of `.gitleaks.toml`, so a change cannot allowlist its own secret; a change that edits
  `.gitleaks.toml` or `.gitleaksignore` gets a note;
- literal values of the local `.env` of 12 or more characters (skipped, with a note, without one);
- added env files: `.env`, `.env.*` and `*.env`, except `*.example`.

Output names the kind, the file and the commit, never a value. Exit code 1 on a finding, 0 when clean,
2 when the scan cannot run (a missing ref, an unreadable `.env` or `.gitleaks.toml`, no git): it then
prints `NOT RUN:` and the reason, never an exception's text.

It does not replace gitleaks: gitleaks has many more rules and, in CI, reads the whole history of every
branch; `scripts/scan_env_values.py` covers the history, pull request heads and GitHub texts.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KEY_SHAPES = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "github_token": re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{30,}"),
    "openai_or_anthropic_key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}"),
    "aws_key_id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    "nvidia_api_key": re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}"),
    "slack_token": re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{10,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
}
# A secret-like name, also at the end of a longer one (GEMINI_API_KEY, DB_PASSWORD), then `=` or `:`.
SECRET_NAME = r"(?i)(?<![A-Za-z0-9])(?:api[_-]?key|secret(?:[_-]?key)?|password|passwd|token)['\"]?\s*[:=]\s*"
# Braces mark a template ("{password}", f-strings), a backslash an escape in a string literal: not a value.
QUOTED_ASSIGNMENT = re.compile(SECRET_NAME + r"""['"][^'"\s{}]{12,}['"]""")
UNQUOTED_ASSIGNMENT = re.compile(SECRET_NAME + r"""(?P<v>[^\s'"`#;,()\[\]{}<>\\]{12,})(?P<call>\(?)""")
# An unquoted value that is code, not a secret: a dotted name, a $variable or an UPPER_CASE constant.
CODE_VALUE = re.compile(r"^(?:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+|\$\w+|[A-Z_][A-Z0-9_]*)$")
POSTGRES_URL = re.compile(r"""postgres(?:ql)?://[^:/@\s"'`]+:(?P<pw>[^@\s"'`]+)@""")
MIN_ENV_LEN = 12
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
COMMIT_MARK = "\x00commit "
FINAL = "final diff"
DIFF_OPTIONS = ("--no-color", "--no-ext-diff", "--no-textconv", "--no-renames", "--text", "-U0",
                "--src-prefix=a/", "--dst-prefix=b/")


class NotRun(Exception):
    """The scan cannot run; the message is ours and holds no value."""


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    where: str = FINAL   # FINAL or a commit hash (10 characters)


@dataclass
class Patch:
    """What a diff text adds: lines by file and by the commit they come from."""
    added: list[tuple[str, str, str]] = field(default_factory=list)   # (where, path, line)
    files: dict[str, str] = field(default_factory=dict)              # path on the new side -> where first seen
    touched: set[str] = field(default_factory=set)                   # every path a diff names
    binary: set[str] = field(default_factory=set)
    commits: list[str] = field(default_factory=list)


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


def parse_allowlists(text: str | None) -> list[Allowlist]:
    """The allowlists of the `postgres-url-password` rule in a `.gitleaks.toml` text; none without one."""
    if not text:
        return []
    rules = tomllib.loads(text).get("rules", [])
    rule = next((r for r in rules if r.get("id") == "postgres-url-password"), None)
    if rule is None:
        return []
    entries = rule.get("allowlists") or ([rule["allowlist"]] if "allowlist" in rule else [])
    return [Allowlist(tuple(re.compile(p) for p in e.get("paths", [])), tuple(re.compile(r) for r in e.get("regexes", [])))
            for e in entries]


def env_value(raw: str) -> str:
    """The value of `KEY=value`: inside its quotes when quoted, else up to an inline ` #` comment."""
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        return raw[1:end] if end > 0 else raw[1:]
    return re.split(r"\s#", raw, maxsplit=1)[0].strip()


def load_env_values(env: Path) -> dict[str, str]:
    """Name -> value for every value of MIN_ENV_LEN or more characters; empty without the file."""
    if not env.exists():
        return {}
    values = {}
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw = line.split("=", 1)
        value = env_value(raw)
        if len(value) >= MIN_ENV_LEN:
            values[name.strip()] = value
    return values


def is_env_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".example"):
        return False
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run git; stdout is decoded here, so a stray carriage return stays inside its line."""
    done = subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=false", *args], capture_output=True, check=check)
    done.stdout = done.stdout.decode("utf-8", errors="replace")
    return done


def require_ref(repo: Path, ref: str) -> str:
    """The full hash of `ref`, or NotRun naming the ref and the command that fetches it."""
    if ref.startswith("-"):
        raise NotRun(f"'{ref}' is not a ref (it starts with '-')")
    done = git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}", check=False)
    if done.returncode == 0:
        return done.stdout.strip()
    if ref.startswith("refs/pull/"):
        how = f'git fetch origin "+{ref}:{ref}"'
    elif ref.startswith("origin/"):
        how = f'git fetch origin "+refs/heads/{ref[7:]}:refs/remotes/{ref}"'
    else:
        how = "git fetch origin, or check the name"
    raise NotRun(f"ref {ref} is not in this repository; fetch it with: {how}")


ESCAPES = {"n": 10, "t": 9, "r": 13, "\\": 92, '"': 34, "a": 7, "b": 8, "f": 12, "v": 11}


def unquote_path(raw: str) -> str:
    """A path as a diff header prints it: git quotes an unusual name C-style ("a\\tb", octal UTF-8 bytes)."""
    raw = raw.rstrip("\t")
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return raw
    body, out, i = raw[1:-1], bytearray(), 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            if re.fullmatch(r"[0-7]{3}", body[i + 1:i + 4]):
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
            else:
                out.append(ESCAPES.get(body[i + 1], ord(body[i + 1]) & 0xFF))
                i += 2
            continue
        out += body[i].encode("utf-8")
        i += 1
    return out.decode("utf-8", errors="replace")


def strip_side(target: str) -> str:
    return target[2:] if target.startswith(("a/", "b/")) else target


def header_path(rest: str) -> str:
    """The path of `diff --git a/X b/X` (renames are off, so both sides name the same file)."""
    if rest.endswith('"'):
        start = rest.rfind(' "')
        return strip_side(unquote_path(rest[start + 1:] if start >= 0 else rest))
    n = (len(rest) - 5) // 2   # "a/X b/X" is 2 * len(X) + 5 characters
    if len(rest) >= 5 and (len(rest) - 5) % 2 == 0 and rest[2 + n:5 + n] == " b/":
        return rest[5 + n:]
    cut = rest.rfind(" b/")
    return rest[cut + 3:] if cut >= 0 else rest


def parse_patch(text: str, where: str = FINAL, patch: Patch | None = None) -> Patch:
    """The added lines of a unified diff, as `git diff` or `git log -p` prints it with DIFF_OPTIONS.

    A hunk is read by the line counts of its `@@` header, so an added line that itself starts with
    `++ ` or `+++ b/` is content, never a file name. A line COMMIT_MARK + hash between diffs sets the
    commit that the following diffs belong to."""
    patch = patch if patch is not None else Patch()
    state, path, old_left, new_left = "outside", "", 0, 0
    for line in text.split("\n"):
        if state == "hunk" and (old_left > 0 or new_left > 0):
            tag = line[:1]
            if tag == "+" and new_left > 0:
                patch.added.append((where, path, line[1:].rstrip("\r")))
                new_left -= 1
                continue
            if tag == "-" and old_left > 0:
                old_left -= 1
                continue
            if tag == " " and old_left > 0 and new_left > 0:
                old_left, new_left = old_left - 1, new_left - 1
                continue
            if tag == "\\":
                continue
            state = "outside"   # the counts do not fit this line: read it as a header
        if line.startswith(COMMIT_MARK):
            where, state = line[len(COMMIT_MARK):].strip()[:10], "outside"
            patch.commits.append(where)
            continue
        if line.startswith("diff --git "):
            state, path = "header", header_path(line[len("diff --git "):])
            patch.touched.add(path)
            continue
        if state == "outside":
            continue
        hunk = HUNK.match(line)
        if hunk:
            old_left = int(hunk.group(1)) if hunk.group(1) is not None else 1
            new_left = int(hunk.group(2)) if hunk.group(2) is not None else 1
            state = "hunk"
            continue
        if state != "header":
            continue
        if line.startswith("+++ "):
            target = unquote_path(line[4:])
            path = "" if target == "/dev/null" else strip_side(target)
            if path:
                patch.files.setdefault(path, where)
        elif line.startswith("new file mode"):
            patch.files.setdefault(path, where)   # an empty new file has no `+++` line
        elif line.startswith(("Binary files ", "GIT binary patch")):
            patch.binary.add(path)
    return patch


def read_patch(repo: Path, since: str, head: str, net_only: bool) -> Patch:
    """The final diff since..head and, unless net_only, every commit in since..head as well."""
    patch = parse_patch(git(repo, "diff", *DIFF_OPTIONS, "--end-of-options", since, head).stdout)
    if not net_only:
        done = git(repo, "log", "-p", *DIFF_OPTIONS, "--diff-merges=remerge", "--format=%x00commit %H",
                   "--end-of-options", f"{since}..{head}", check=False)
        if done.returncode != 0:
            raise NotRun("git log --diff-merges=remerge failed; it needs git 2.36 or newer (or use --net-only)")
        parse_patch(done.stdout, patch=patch)
    return patch


def secret_value_unquoted(text: str) -> bool:
    for m in UNQUOTED_ASSIGNMENT.finditer(text):
        value = m.group("v")
        if m.group("call") or CODE_VALUE.match(value):
            continue
        if re.search(r"[A-Za-z]", value) and re.search(r"\d", value):
            return True
    return False


def scan(patch: Patch, env_values: dict[str, str], allowlists: list[Allowlist]) -> list[Finding]:
    found: set[Finding] = set()
    for where, path, text in patch.added:
        for kind, rx in KEY_SHAPES.items():
            if rx.search(text):
                found.add(Finding(kind, path, where))
        if QUOTED_ASSIGNMENT.search(text):
            found.add(Finding("secret_assignment", path, where))
        if secret_value_unquoted(text):
            found.add(Finding("secret_assignment_unquoted", path, where))
        for m in POSTGRES_URL.finditer(text):
            if not any(a.allows(path, m.group("pw")) for a in allowlists):
                found.add(Finding("postgres_url_with_password", path, where))
        for name, value in env_values.items():
            if value in text:
                found.add(Finding(f"env_value:{name}", path, where))
    for path, where in patch.files.items():
        if is_env_file(path):
            found.add(Finding("env_file", path, where))
    return sorted(found, key=lambda f: (f.path, f.kind, f.where != FINAL, f.where))


def places(wheres: list[str], commits: list[str]) -> str:
    """`final diff; commits a, b, c (+N more)`: where one kind of finding in one file was seen."""
    order = {c: i for i, c in enumerate(commits)}
    parts = [FINAL] if FINAL in wheres else []
    seen = sorted((w for w in wheres if w != FINAL), key=lambda w: order.get(w, len(order)))
    if seen:
        more = f" (+{len(seen) - 5} more)" if len(seen) > 5 else ""
        parts.append(("commit " if len(seen) == 1 else "commits ") + ", ".join(seen[:5]) + more)
    return "; ".join(parts)


def run(args: argparse.Namespace) -> int:
    if shutil.which("git") is None:
        raise NotRun("git is not installed or not on PATH")
    repo = Path(args.repo)
    if git(repo, "rev-parse", "--git-dir", check=False).returncode != 0:
        raise NotRun(f"{repo} is not a git repository")
    if args.range is not None:
        if args.range.count("..") != 1 or "..." in args.range:
            raise NotRun("--range needs exactly A..B")
        lo, hi = args.range.split("..")
        since, head = require_ref(repo, lo), require_ref(repo, hi)
        label = f"range {lo}..{hi}"
    else:
        head_ref = f"refs/pull/{args.pr}/head" if args.pr is not None else args.head
        head = require_ref(repo, head_ref)
        base = require_ref(repo, args.base)
        since = git(repo, "merge-base", base, head, check=False).stdout.strip()
        if not since:
            raise NotRun(f"{head_ref} and {args.base} have no common history")
        label = f"{'#' + str(args.pr) if args.pr is not None else head_ref} at {head[:7]} vs {args.base}"

    if args.gitleaks_config:
        config_text, config_from = Path(args.gitleaks_config).read_text(encoding="utf-8"), args.gitleaks_config
    else:
        shown = git(repo, "show", f"{since}:.gitleaks.toml", check=False)
        config_text = shown.stdout if shown.returncode == 0 else None
        config_from = f".gitleaks.toml at the base {since[:7]}" if config_text else "none (the base has no .gitleaks.toml)"
    allowlists = parse_allowlists(config_text)
    env_values = load_env_values(repo / args.env)

    patch = read_patch(repo, since, head, args.net_only)
    found = scan(patch, env_values, allowlists)
    groups: dict[tuple[str, str], list[str]] = {}
    for f in found:
        groups.setdefault((f.kind, f.path), []).append(f.where)
    files = sum(1 for where in patch.files.values() if where == FINAL)
    lines = sum(1 for where, _, _ in patch.added if where == FINAL)
    commits = "commits not read (--net-only)" if args.net_only else f"{len(patch.commits)} commits read"
    total = f"{len(groups)}" + (f" ({len(found)} places)" if len(found) != len(groups) else "")
    print(f"{label}: {files} files, {lines} added lines; {commits}; findings: {total}")
    print(f"  allowlist: {config_from}")
    if not env_values:
        print("  note: no .env values loaded, so the literal check was skipped")
    edited = sorted(p for p in patch.touched if p.rsplit("/", 1)[-1] in (".gitleaks.toml", ".gitleaksignore"))
    if edited:
        print(f"  note: this change edits {', '.join(edited)}; the scan uses the base's allowlist, not these edits")
    if patch.binary:
        print(f"  skipped {len(patch.binary)} binary files: {', '.join(sorted(patch.binary))}")
    for (kind, path), wheres in groups.items():
        print(f"  {kind} in {path}: {places(wheres, patch.commits)}")
    return 1 if found else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--pr", type=int, help="scan refs/pull/<N>/head against --base")
    target.add_argument("--range", help="scan what A..B added")
    parser.add_argument("--base", default="origin/dev", help="the branch the head will merge into")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--net-only", action="store_true", help="read the final diff only, not every commit")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--gitleaks-config", help="read the allowlist from this file, not from the base's copy")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except NotRun as exc:
        print(f"NOT RUN: {exc}")
    except subprocess.CalledProcessError as exc:
        print(f"NOT RUN: git {exc.cmd[5] if len(exc.cmd) > 5 else ''} failed (exit {exc.returncode})")
    except Exception as exc:  # noqa: BLE001 - the class name only: an exception's text may hold a value
        print(f"NOT RUN: {type(exc).__name__}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
