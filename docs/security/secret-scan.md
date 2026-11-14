# Secret scan

Two checks prove that no secret is in the repository, its history or its GitHub texts. Both print locations and variable names only, never a value.

| Check | What it covers | Where it runs |
|---|---|---|
| gitleaks 8.30.1 with `.gitleaks.toml` and `.gitleaksignore` | Every commit of every branch and tag: built-in key rules plus a rule for database URLs with a password | CI, on every pull request and push to `dev` and `main` (job "Secret scan"). Locally with the command below, which also covers pull request heads. |
| `scripts/scan_env_values.py` | The values of the local `.env` (12 or more characters), and the password of a URL value, searched as literals in: <br>• `git log --all -p`, including merge diffs and pull request heads; <br>• ref names; <br>• issue and PR titles, bodies, comments, review comments, review summaries, and earlier versions of edited bodies and comments (GitHub API). <br>It also looks for common key shapes in the GitHub texts. | Locally only, because it needs the real `.env`. It is never committed or sent anywhere. |

`.gitleaks.toml` and the CI job come from #83 (PR #94). They are in `dev`, and the gitleaks parts of this page apply once they reach `main`.

## A branch before a merge, without CI

`scripts/scan_diff_secrets.py` (#472) reads only the lines a branch adds. It is the check to run when the CI secret scan cannot run, and a quick one before any merge:

```
git fetch origin "+refs/heads/*:refs/remotes/origin/*" "+refs/pull/*/head:refs/pull/*/head"
python scripts/scan_diff_secrets.py --pr 443                  # a pull request head against origin/dev
python scripts/scan_diff_secrets.py --base origin/dev         # the current branch against origin/dev
python scripts/scan_diff_secrets.py --range A..B              # what a range of commits added
```

What it reads:
- by default, every commit from the merge base to the head, and the final diff. A secret that one commit adds and a later one removes is still found: a merge commit brings that history into `dev` and `main`;
- a merge commit as its diff against its first parent, which also shows lines written while resolving it;
- `--net-only`: the final diff alone;
- added lines only, binary files read as text.

What it reports:
- common key shapes, and values assigned to a key, secret, password or token name, quoted or not (`export API_TOKEN=...`, `password: ...`);
- database URLs with a password that the allowlist does not cover (path and value together). The allowlist is the base's copy of `.gitleaks.toml`, so a branch cannot allowlist its own value; a branch that edits `.gitleaks.toml` or `.gitleaksignore` gets a note;
- literal values of the local `.env`;
- added env files: `.env`, `.env.*`, `*.env`, except `*.example`.

Output: one line per kind and file, with the commits it was seen in. Never a value. Exit codes:
- 1 on a finding;
- 0 when clean;
- 2 when it cannot run: a missing ref (named, with the fetch command), an unreadable `.env` or `.gitleaks.toml`, or no git. It then prints `NOT RUN:` and the reason.

It does not replace gitleaks, which has many more rules and reads the whole history in CI. The history, pull request heads and GitHub texts are covered by `scan_env_values.py` below.

## Before the repository goes public

Run both checks right before the switch, from the main checkout with an up-to-date `.env`:

```
git fetch --prune origin "+refs/heads/*:refs/remotes/origin/*" "+refs/tags/*:refs/tags/*" "+refs/pull/*/head:refs/pull/*/head"
gitleaks git --config .gitleaks.toml --log-opts="--all" --redact --no-banner .
python scripts/scan_env_values.py
```

- The first line also fetches the head of every pull request, closed ones included. Those refs become public with the repository, even when their branch was deleted. The script runs the same fetch itself unless it gets `--no-fetch`.
- Both checks must end clean: `no leaks found`, and `RESULT: clean` with `0 / 0 / 0` for every variable.
- The script exits 2 and prints `NOT RUN` when it loads no value, for example from an empty or missing `.env`.

**If anything is found**:
- the key counts as leaked, even if the repository is still private;
- tell the team lead at once with the location only: file, commit, PR or comment, and variable name;
- rotate the key;
- do not rewrite history without a team decision.

The allowlist in `.gitleaks.toml` holds only synthetic test values, each limited to its file and with a reason. `.gitleaksignore` holds the one fake planted on purpose. Never add a real value to either.

## Limits

The checks do not cover:
- **Actions logs.** CI uses no secrets, so they hold none, but they are not scanned.
- **Values under 12 characters**, and `.env` values that changed before the scan: only today's values are known.
- **Encoded forms**: base64, URL-encoding or a value split across lines. The one exception is the decoded form of a URL password.
- **GitHub content outside the API texts listed above**: review comment edit histories beyond what `userContentEdits` returns (at most 50 versions per body, 20 per comment or review), commit comments, releases, the wiki (off) and discussions (off).
- **Objects that no ref reaches** but that GitHub still serves by SHA, such as a force-pushed commit. There are none as long as nobody force-pushes, which the team rules forbid outside one's own branch.
- **Forks.** There are none while the repository is private.

## Last result

Run on 2026-11-14 at about 02:00 Helsinki. The PR for #82 quotes the same output.

| Check | Result |
|---|---|
| gitleaks 8.30.1 in CI | `no leaks found` on PR #115 (after the allowlist follow-up for a moved test canary) |
| `postgres://` URLs with a password, every ref including PR heads | 18 distinct. 17 are allowlisted synthetic test values; 1 is the planted fake of PR #96 in `.gitleaksignore`. None equals a `.env` value. |
| `scan_env_values.py` | 11 values (10 of 12+ characters and the `DATABASE_URL` password): 0 hits each, across 232 commits, 104 refs (63 PR heads) and 391 GitHub texts, earlier versions included. Key shapes in GitHub texts: 0. Eight postgres URLs in the bodies of PRs #39, #74 and #115, and in earlier versions of them, are allowlisted synthetic test markers. |
| Self-check | `scan_env_values.py` with a fake value on a local branch that was never pushed: `1` hit, exit 1. An empty `.env`: `NOT RUN`, exit 2. gitleaks with a fake postgres URL on scratch branch `r/83-ci-failproof`: `leaks found: 1` for rule `postgres-url-password`, job failed. That branch was pushed for the CI run (PR #96) and then closed and deleted. |
