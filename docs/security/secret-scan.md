# Secret scan

Two checks prove that no secret is in the repository, its history or its GitHub texts. Both print locations and variable names only, never a value.

| Check | What it covers | Where it runs |
|---|---|---|
| gitleaks 8.30.1 with `.gitleaks.toml` | Every commit of every branch and tag: built-in key rules plus a rule for database URLs with a password | CI on every pull request and push to `dev` and `main` (`.github/workflows/ci.yml`, job "Secret scan") |
| `scripts/scan_env_values.py` | The values of the local `.env` (12 or more characters) as literals in: <br>• `git log --all -p`, including what each merge changed; <br>• branch and tag names; <br>• issue and pull request titles, bodies, comments and review comments (GitHub API). <br>It also looks for common key shapes in the GitHub texts. | Locally only, because it needs the real `.env`. It is never committed or sent anywhere. |

## Before the repository goes public

Run both checks right before the switch, from the main checkout with an up-to-date `.env`:

```
git fetch --all --tags --prune
gitleaks git --config .gitleaks.toml --log-opts="--all" --redact --no-banner .
python scripts/scan_env_values.py
```

- Instead of a local gitleaks you can use the result of the latest CI run on `dev`: its secret-scan job runs the same command over every remote branch.
- Both must end clean: `no leaks found`, and `RESULT: clean` with `0 / 0 / 0` for every variable.

**If anything is found**:
- the key counts as leaked, even if the repository is still private;
- tell the team lead at once with the location only: file, commit, PR or comment, and variable name;
- rotate the key;
- do not rewrite history without a team decision.

The allowlist in `.gitleaks.toml` holds only synthetic test values, each limited to its file and with a reason. Never add a real value to it.

## Last result

Run on 2026-11-14 before 01:00 Helsinki:

| Check | Result |
|---|---|
| gitleaks 8.30.1 (CI run on PR #94) | `116 commits scanned. no leaks found`: every non-merge commit of the 9 remote branches |
| `scan_env_values.py` | `.env` values: 0 hits for all 10 values of 12+ characters, across 192 commits of all refs (merges included), 25 ref names and 283 GitHub texts. Key shapes in GitHub texts: 0. Three postgres URLs in the descriptions of PRs #39 and #74 are the synthetic markers of the log-mask tests. |
| Self-check | A fake value on a local branch that was never pushed: the script reports `1` hit and exits 1. A fake postgres URL on a scratch branch: CI's gitleaks job reports `leaks found: 1` for rule `postgres-url-password` and fails. |
