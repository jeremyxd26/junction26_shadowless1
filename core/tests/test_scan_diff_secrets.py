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


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                           "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True).stdout


def commit(repo: Path, files: dict[str, str], message: str = "change") -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)
    return run_git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    run_git(tmp_path, "init", "-q", "-b", "main")
    allowlist = (
        "[[rules]]\n"
        'id = "postgres-url-password"\n'
        "regex = '''x'''\n"
        "    [[rules.allowlists]]\n"
        "    condition = \"AND\"\n"
        "    paths = ['''^tests/fixture\\.py$''']\n"
        f"    regexes = ['''^({SYNTHETIC})$''']\n"
    )
    commit(tmp_path, {"README.md": "base\n", ".gitleaks.toml": allowlist}, "base")
    run_git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def scan_head(repo: Path) -> list:
    files, added = scanner.added_lines(repo, "main", "HEAD")
    return scanner.scan(files, added, scanner.load_env_values(repo / ".env"),
                        scanner.load_allowlists(repo / ".gitleaks.toml"))


def test_a_clean_change_has_no_findings(repo):
    commit(repo, {"app.py": "print('hello')\n"})
    assert scan_head(repo) == []
    assert scanner.main(["--repo", str(repo), "--base", "main"]) == 0


def test_a_database_url_with_a_password_is_found_and_never_printed(repo, capsys):
    commit(repo, {"app.py": f"URL = '{FAKE_URL}'\n"})
    assert [f.kind for f in scan_head(repo)] == ["postgres_url_with_password"]
    assert scanner.main(["--repo", str(repo), "--base", "main"]) == 1
    out = capsys.readouterr().out
    assert "postgres_url_with_password in app.py" in out and FAKE_PASSWORD not in out


def test_the_gitleaks_allowlist_applies_path_and_value_together(repo):
    url = SCHEME + "coach:" + SYNTHETIC + "@127.0.0.1:1/coach"
    commit(repo, {"tests/fixture.py": f"URL = '{url}'\n"})
    assert scan_head(repo) == []                                   # synthetic value in its allowlisted file
    commit(repo, {"app.py": f"URL = '{url}'\n"})
    assert [(f.kind, f.path) for f in scan_head(repo)] == [("postgres_url_with_password", "app.py")]


def test_key_shapes_are_found(repo):
    commit(repo, {"config.py": f"KEY_ID = '{AWS_LIKE}'\n"})
    assert "aws_key_id" in {f.kind for f in scan_head(repo)}


def test_a_literal_env_value_and_an_added_env_file_are_found(repo, capsys):
    (repo / ".env").write_text(f"FAKE_TOKEN={ENV_VALUE}\nSHORT=tooshort\n", encoding="utf-8")
    commit(repo, {"settings.py": f"TOKEN = '{ENV_VALUE}'\n", "deploy/.env.prod": "X=1\n"})
    kinds = {(f.kind, f.path) for f in scan_head(repo)}
    assert ("env_value:FAKE_TOKEN", "settings.py") in kinds
    assert ("env_file", "deploy/.env.prod") in kinds and ("env_file", ".env") in kinds
    scanner.main(["--repo", str(repo), "--base", "main"])
    assert ENV_VALUE not in capsys.readouterr().out


def test_only_added_lines_count(repo):
    run_git(repo, "checkout", "-q", "main")
    commit(repo, {"old.py": f"URL = '{FAKE_URL}'\n"}, "already on main")
    run_git(repo, "checkout", "-q", "-b", "later")
    commit(repo, {"new.py": "print('fine')\n"})
    assert scan_head(repo) == []                                   # the old line is not part of this branch


def test_a_commit_range(repo):
    before = run_git(repo, "rev-parse", "HEAD").strip()
    after = commit(repo, {"app.py": f"URL = '{FAKE_URL}'\n"})
    assert scanner.main(["--repo", str(repo), "--range", f"{before}..{after}"]) == 1


def test_an_unknown_ref_cannot_run(repo):
    assert scanner.main(["--repo", str(repo), "--base", "no-such-branch"]) == 2
