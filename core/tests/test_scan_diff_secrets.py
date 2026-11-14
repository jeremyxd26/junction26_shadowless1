"""scripts/scan_diff_secrets.py (#472) on a temporary git repository with planted fakes.

Every fake is built from parts at run time, so this file holds no secret and no literal database URL with
a password: neither the local commit hook nor gitleaks should ever see one here.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("scan_diff_secrets", ROOT / "scripts" / "scan_diff_secrets.py")
scanner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scanner   # dataclasses look the module up by name
SPEC.loader.exec_module(scanner)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

SCHEME = "postgres" + "ql://"
FAKE_PASSWORD = "fake" + "-only-" + "pw42"
FAKE_URL = SCHEME + "demo:" + FAKE_PASSWORD + "@db.invalid/x"
SYNTHETIC = "not-a-" + "real-password"
AWS_LIKE = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
ENV_VALUE = "fake" + "-env-value-" + "0123456789"
TOKEN_LIKE = "fake" + "Tok3n" + "Value98765"
NVIDIA_LIKE = "nv" + "api-" + "fakeOnly" + "0123456789" * 3
ALLOWLIST = (
    "[[rules]]\n"
    'id = "postgres-url-password"\n'
    "regex = '''x'''\n"
    "    [[rules.allowlists]]\n"
    "    condition = \"AND\"\n"
    "    paths = ['''{path}''']\n"
    "    regexes = ['''^({value})$''']\n"
)


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                           "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
                          capture_output=True, text=True, check=True).stdout


def write(repo: Path, files: dict[str, str | bytes]) -> None:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")


def commit(repo: Path, files: dict[str, str | bytes], message: str = "change") -> str:
    write(repo, files)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return run_git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    run_git(tmp_path, "init", "-q", "-b", "main")
    allowlist = ALLOWLIST.format(path=r"^tests/fixture\.py$", value=SYNTHETIC)
    commit(tmp_path, {"README.md": "base\n", ".gitleaks.toml": allowlist}, "base")
    run_git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def scan_head(repo: Path, net_only: bool = False) -> list:
    head = run_git(repo, "rev-parse", "HEAD").strip()
    since = run_git(repo, "merge-base", "main", head).strip()
    allowlists = scanner.parse_allowlists(run_git(repo, "show", f"{since}:.gitleaks.toml"))
    patch = scanner.read_patch(repo, since, head, net_only)
    return scanner.scan(patch, scanner.load_env_values(repo / ".env"), allowlists)


def kinds(findings: list) -> set:
    return {(f.kind, f.path) for f in findings}


def main_out(capsys, *argv: str) -> tuple[int, str]:
    code = scanner.main(list(argv))
    return code, capsys.readouterr().out


def test_a_clean_change_has_no_findings(repo, capsys):
    commit(repo, {"app.py": "print('hello')\n"})
    assert scan_head(repo) == []
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main")
    assert code == 0
    assert "1 files, 1 added lines; 1 commits read; findings: 0" in out
    assert "note: no .env values loaded" in out


def test_a_database_url_with_a_password_is_found_and_never_printed(repo, capsys):
    sha = commit(repo, {"app.py": f"URL = '{FAKE_URL}'\n"})
    found = scan_head(repo)
    assert {(f.kind, f.path, f.where) for f in found} == {
        ("postgres_url_with_password", "app.py", "final diff"),
        ("postgres_url_with_password", "app.py", sha[:10]),
    }
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main")
    assert code == 1
    assert f"postgres_url_with_password in app.py: final diff; commit {sha[:10]}" in out
    assert FAKE_PASSWORD not in out


def test_the_gitleaks_allowlist_applies_path_and_value_together(repo):
    url = SCHEME + "coach:" + SYNTHETIC + "@127.0.0.1:1/coach"
    commit(repo, {"tests/fixture.py": f"URL = '{url}'\n"})
    assert scan_head(repo) == []                                   # synthetic value in its allowlisted file
    commit(repo, {"app.py": f"URL = '{url}'\n"})
    assert kinds(scan_head(repo)) == {("postgres_url_with_password", "app.py")}


def test_the_allowlist_comes_from_the_base_so_a_change_cannot_allowlist_itself(repo, capsys):
    widened = ALLOWLIST.format(path=r"^app\.py$", value=FAKE_PASSWORD)
    commit(repo, {".gitleaks.toml": widened, "app.py": f"URL = '{FAKE_URL}'\n"})
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main")
    assert code == 1
    assert "postgres_url_with_password in app.py" in out
    assert "note: this change edits .gitleaks.toml; the scan uses the base's allowlist, not these edits" in out


def test_with_a_given_config_the_note_names_that_file(repo, capsys, tmp_path):
    """#604: with --gitleaks-config the scan reads that file, so the note names it, not the base's copy."""
    widened = ALLOWLIST.format(path=r"^app\.py$", value=FAKE_PASSWORD)
    commit(repo, {".gitleaks.toml": widened, "app.py": f"URL = '{FAKE_URL}'\n"})
    given = tmp_path / "given-gitleaks.toml"
    given.write_text(ALLOWLIST.format(path=r"^tests/fixture\.py$", value=SYNTHETIC), encoding="utf-8")
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main", "--gitleaks-config", str(given))
    assert code == 1 and "postgres_url_with_password in app.py" in out
    assert f"  allowlist: {given}" in out
    assert f"note: this change edits .gitleaks.toml; the scan uses {given}, not these edits" in out
    assert "the base's allowlist" not in out


def test_key_shapes_and_assignments_are_found(repo):
    commit(repo, {
        "config.py": f"KEY_ID = '{AWS_LIKE}'\n",
        "deploy/run.sh": f"export API_TOKEN={TOKEN_LIKE}\n",
        "deploy/values.yaml": f"password: {TOKEN_LIKE}\n",
        "settings.py": f'GEMINI_API_KEY = "{TOKEN_LIKE}"\n',
        "notes.txt": f"the reader's key was {NVIDIA_LIKE} until today\n",
    })
    found = kinds(scan_head(repo, net_only=True))
    assert ("aws_key_id", "config.py") in found
    assert ("nvidia_api_key", "notes.txt") in found
    assert ("secret_assignment_unquoted", "deploy/run.sh") in found
    assert ("secret_assignment_unquoted", "deploy/values.yaml") in found
    assert ("secret_assignment", "settings.py") in found


def test_code_and_placeholders_are_not_assignments(repo):
    commit(repo, {
        "app.py": ("token = settings.gemini_token_v2\n"
                   "api_key = load_api_key_from_disk2()\n"
                   "password = DEFAULT_PASSWORD_V2\n"
                   "max_tokens = 1200000000000\n"
                   "token_url = 'https://example.invalid/oauth2/token'\n"),
        "compose.yaml": "password: ${DB_PASSWORD}\nsecret: $SOME_SECRET_VALUE\n",
        "template.py": 'password = "{db_password_placeholder1}"\nmessage = "token=\\\\nabc"\n',
    })
    assert scan_head(repo) == []


def test_a_literal_env_value_and_added_env_files_are_found(repo, capsys):
    (repo / ".env").write_text(f"FAKE_TOKEN={ENV_VALUE}  # local only\nSHORT=tooshort\n", encoding="utf-8")
    commit(repo, {"settings.py": f"TOKEN = '{ENV_VALUE}'\n", "deploy/.env.prod": "X=1\n", "prod.env": "Y=2\n",
                  "app.env.example": "Z=\n", ".env.example": "Z=\n", "empty/.env": ""})
    found = kinds(scan_head(repo))
    assert ("env_value:FAKE_TOKEN", "settings.py") in found
    assert {p for k, p in found if k == "env_file"} == {".env", "deploy/.env.prod", "prod.env", "empty/.env"}
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main")
    assert code == 1 and ENV_VALUE not in out


def test_only_added_lines_count(repo):
    run_git(repo, "checkout", "-q", "main")
    commit(repo, {"old.py": f"URL = '{FAKE_URL}'\n"}, "already on main")
    run_git(repo, "checkout", "-q", "-b", "later")
    commit(repo, {"old.py": "print('fine')\n"}, "removes the line")
    assert scan_head(repo) == []                                   # a removed line is not an added one


def test_a_secret_removed_by_a_later_commit_is_still_found(repo, capsys):
    added = commit(repo, {"app.py": f"URL = '{FAKE_URL}'\n"}, "add")
    commit(repo, {"app.py": "URL = None\n"}, "remove again")
    assert {(f.kind, f.where) for f in scan_head(repo)} == {("postgres_url_with_password", added[:10])}
    assert scan_head(repo, net_only=True) == []
    assert main_out(capsys, "--repo", str(repo), "--base", "main")[0] == 1
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main", "--net-only")
    assert code == 0 and "commits not read (--net-only)" in out


def test_places_are_grouped_per_kind_and_file():
    commits = [f"{n:010d}" for n in range(8)]
    assert scanner.places(["final diff", commits[2], commits[0]], commits) == "final diff; commits 0000000000, 0000000002"
    assert scanner.places(commits[::-1], commits).endswith("0000000004 (+3 more)")


def test_a_line_written_while_resolving_a_merge_is_found(repo):
    commit(repo, {"a.txt": "feature\n"})
    run_git(repo, "checkout", "-q", "-b", "side", "main")
    commit(repo, {"b.txt": "side\n"})
    run_git(repo, "checkout", "-q", "feature")
    run_git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
    write(repo, {"c.py": f"URL = '{FAKE_URL}'\n"})
    run_git(repo, "add", "c.py")
    run_git(repo, "commit", "-q", "-m", "merge side")
    merge = run_git(repo, "rev-parse", "HEAD").strip()
    found = scan_head(repo)
    assert scanner.Finding("postgres_url_with_password", "c.py", merge[:10]) in found


def test_merging_the_base_into_a_branch_adds_nothing_of_the_base(repo):
    commit(repo, {"a.txt": "feature\n"})
    run_git(repo, "checkout", "-q", "main")
    commit(repo, {"base.py": f"URL = '{FAKE_URL}'\n"}, "already on the base")
    run_git(repo, "checkout", "-q", "feature")
    run_git(repo, "merge", "-q", "--no-ff", "-m", "merge main", "main")
    assert scan_head(repo) == []                                   # the base's line is not the branch's


def test_content_lines_that_look_like_headers_stay_content(repo):
    notes = "++ b/evil.env\n+++ x\n--- a/y\n" + f"URL = '{FAKE_URL}'\n"
    commit(repo, {"notes.md": notes})
    assert kinds(scan_head(repo)) == {("postgres_url_with_password", "notes.md")}


def test_a_stray_carriage_return_does_not_hide_the_next_lines(repo):
    data = b"x = 1\rnext\n" + f"URL = '{FAKE_URL}'\n".encode()
    commit(repo, {"odd.py": data})
    assert kinds(scan_head(repo)) == {("postgres_url_with_password", "odd.py")}


def test_a_binary_file_is_read_as_text(repo, capsys):
    commit(repo, {"blob.bin": b"\x00\x01\x02" + f"{FAKE_URL}\n".encode() + b"\x00"})
    assert kinds(scan_head(repo)) == {("postgres_url_with_password", "blob.bin")}
    assert "binary files" not in main_out(capsys, "--repo", str(repo), "--base", "main")[1]


def test_non_ascii_paths_are_reported_as_written(repo):
    commit(repo, {"café/sécret.py": f"URL = '{FAKE_URL}'\n"})
    assert kinds(scan_head(repo)) == {("postgres_url_with_password", "café/sécret.py")}


def test_quoted_header_paths_are_unquoted():
    assert scanner.unquote_path('"b/caf\\303\\251\\tx.py"') == "b/café\tx.py"
    assert scanner.header_path('"a/x\\ty.py" "b/x\\ty.py"') == "x\ty.py"
    assert scanner.header_path("a/dir b/x.py b/dir b/x.py") == "dir b/x.py"
    diff = ("diff --git \"a/x\\ty.env\" \"b/x\\ty.env\"\nnew file mode 100644\nindex 0000000..e69de29\n"
            "diff --git a/k.py b/k.py\n--- a/k.py\n+++ b/k.py\n@@ -1 +1 @@\n-old\n+new\n\\ No newline at end of file\n")
    patch = scanner.parse_patch(diff)
    assert set(patch.files) == {"x\ty.env", "k.py"}
    assert patch.added == [("final diff", "k.py", "new")]


def test_a_commit_range(repo, capsys):
    before = run_git(repo, "rev-parse", "HEAD").strip()
    after = commit(repo, {"app.py": f"URL = '{FAKE_URL}'\n"})
    code, out = main_out(capsys, "--repo", str(repo), "--range", f"{before}..{after}")
    assert code == 1 and out.startswith(f"range {before}..{after}:")


def test_a_pull_request_head(repo, capsys):
    sha = commit(repo, {"app.py": f"URL = '{FAKE_URL}'\n"})
    run_git(repo, "update-ref", "refs/pull/0/head", sha)
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main", "--pr", "0")
    assert code == 1 and out.startswith(f"#0 at {sha[:7]} vs main:")


@pytest.mark.parametrize("argv, expected", [
    (["--base", "no-such-branch"], "NOT RUN: ref no-such-branch is not in this repository; fetch it with: "),
    (["--pr", "8"], 'NOT RUN: ref refs/pull/8/head is not in this repository; fetch it with: '
                    'git fetch origin "+refs/pull/8/head:refs/pull/8/head"'),
    (["--base", "origin/gone"], 'git fetch origin "+refs/heads/gone:refs/remotes/origin/gone"'),
    (["--base=--output=x"], "NOT RUN: '--output=x' is not a ref"),
    (["--range", "a...b"], "NOT RUN: --range needs exactly A..B"),
])
def test_a_scan_that_cannot_run_says_why(repo, capsys, argv, expected):
    code, out = main_out(capsys, "--repo", str(repo), *argv)
    assert code == 2 and expected in out


def test_unreadable_inputs_cannot_run_and_print_no_value(repo, capsys, tmp_path):
    commit(repo, {"app.py": "print('x')\n"})
    (repo / ".env").write_bytes(b"FAKE=\xff\xfe" + ENV_VALUE.encode() + b"\n")
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main")
    assert (code, out.strip()) == (2, "NOT RUN: UnicodeDecodeError")
    (repo / ".env").unlink()
    broken = tmp_path / "broken.toml"
    broken.write_text(f"[[rules]\nid = '{FAKE_PASSWORD}'\n", encoding="utf-8")
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main", "--gitleaks-config", str(broken))
    assert (code, out.strip()) == (2, "NOT RUN: TOMLDecodeError")
    code, out = main_out(capsys, "--repo", str(tmp_path / "nowhere"), "--base", "main")
    assert code == 2 and "is not a git repository" in out


def test_without_git_it_cannot_run(repo, capsys, monkeypatch):
    monkeypatch.setattr(scanner.shutil, "which", lambda name: None)
    code, out = main_out(capsys, "--repo", str(repo), "--base", "main")
    assert (code, out.strip()) == (2, "NOT RUN: git is not installed or not on PATH")
