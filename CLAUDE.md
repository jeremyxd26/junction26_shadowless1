# How agents work in this repo

Two people build this project during a hackathon. Each person runs one **coordinator** Claude Code session and several **worker** sessions on their own machine. Sessions on different machines cannot message each other. The only shared state is this repository and its GitHub Issues and PRs.

## Roles
- **Coordinator** works in the main checkout on `main`. It plans the work, files issues, dispatches tasks to its workers by message, reviews their PRs and merges them. It writes no feature code itself.
- **Worker** works in its own git worktree. It does one claimed issue at a time on its own branch and reports back to its coordinator.
- **Humans** own product decisions, the interface contract between areas, and anything irreversible.

## Task board = GitHub Issues
- Every piece of work is an issue with these sections: Goal, Acceptance criteria (checkable), How to verify, Out of scope.
- Every issue has one area label: `area:core`, `area:product` or `area:contract`.
- One issue should be small: about 2 hours of agent work or less.
- **Claim before you work.** Run `gh issue view <N> --json assignees,labels`.
  - If the issue is assigned to someone else or carries `in-progress`, do not touch it.
  - Otherwise run `gh issue edit <N> --add-assignee @me --add-label in-progress` and comment `claimed by <session-name>`.
- When the PR is open, swap `in-progress` for `review`.
- If you are blocked, add the `blocked` label and comment why.
- Found other work while on a task? Open a new issue. Do not fix it in passing.

## Areas and ownership
| Area | Paths | Owner |
|---|---|---|
| core | `core/` — data loading, spending baskets, deterministic tools, coach API | Renat (branch prefix `r/`) |
| product | `app/` — mobile-first web app | Maxim (branch prefix `m/`) |
| contract | `contracts/` — API contract between core and app | both |

- Only change files in another person's area through an issue assigned to you, and say so in the PR.
- Contract changes need an approving review from the other person before merge.

## Branches, commits, PRs
- Branch names: `<owner-prefix>/<issue>-<short-slug>`, for example `r/12-ingest-api`. Always branch from fresh `origin/main`.
- Commit messages: imperative summary plus `(#<issue>)`.
- Before pushing, run `git fetch origin && git rebase origin/main`, then rerun the checks. You may force-push your own branch only with `--force-with-lease`.
- Keep PRs small. The PR body contains:
  - `Closes #<N>`
  - what changed
  - **how it was verified, with the command output pasted**
  - risks and follow-ups
- Merge with squash.
- Never use `--no-verify`. If the local pre-commit check blocks a commit, fix the cause; if you can't, report it to your coordinator.
- Never:
  - push to `main` directly
  - rewrite `main` history
  - force-push or delete other people's branches
  - change git config (author identity)

## Definition of done
- Every acceptance criterion is met.
- Tests and the README run command pass, and their output is in the PR.
- No secrets, no unrelated changes, and `main` still runs with one command.

Do not say "done" without this evidence.

## Secrets and data
- Secrets are loaded only from environment variables in `.env`, which is gitignored. Never put keys in code, logs, issues, PRs or commit messages.
- The repository is public under MIT. Use synthetic data only; no personal data.

## Partner APIs and keys
- Keys live in `.env`; `.env.example` lists the variable names. Read them only via environment variables.
- The main checkout's `.env` is the single source of truth. It is copied into every worktree at session start. After editing it, run `bash .claude/hooks/sync-env.sh`. Never edit `.env` inside a worktree.
- Never print a key, never paste it into a command line shown in a PR or issue, and never write it into a file other than `.env`.
- Some credits are limited and some plans are paid. Before any bulk or batch job against an external API (more than ~100 calls, crawls, GPU jobs), ask your coordinator.
- Cache API responses locally during development, so repeated runs don't spend credits.
- If a key is missing or rejected, report it. Do not sign up for services or buy plans yourself.

## Style of work
- Read the relevant code before changing it, and follow existing patterns.
- No drive-by refactors, renames or dependency changes outside the issue.
- If a product question is unclear, ask your coordinator or human. Don't guess.
- Write issues, PRs, commits and code comments in English.
- Record significant decisions as one line each in `docs/process-log.md`: time, decision, why.
