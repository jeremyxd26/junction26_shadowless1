# How agents work in this repo

Two people build this project during a hackathon. Each person runs one **coordinator** Claude Code session and several **worker** sessions on their own machine. Sessions on different machines cannot message each other. The only shared state is this repository and its GitHub Issues and PRs.

## Roles
- **Coordinator** works in the main checkout on `main`. It plans the work, files issues, dispatches tasks to its workers by message, and reviews their PRs. After a reviewer verdict PASS it merges the PR into `dev`; once the change has passed on the dev environment it merges the same branch into `main`. It writes no feature code itself.
- **Worker** works in its own git worktree. It does one claimed issue at a time on its own branch and reports back to its coordinator. Workers never merge.
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
- A PR that changes `contracts/` carries the `area:contract` label. It also gets a comment that mentions the other person, with a three-line summary of what changed for their side. It is merged after the reviewer verdict PASS, without waiting for an approval. The other person asks for changes through a new issue.

## Branches, commits, PRs
Two long-lived branches:
- `main` is demo-ready. Only tested work gets here.
- `dev` is integration. It is deployed to the dev environment and tested there.

Flow for every change:
1. Branch from fresh `origin/main`, never from `dev`. Name it `<owner-prefix>/<issue>-<short-slug>`, for example `r/12-ingest-api`.
2. Before pushing, run `git fetch origin && git rebase origin/main`, then rerun the checks. You may force-push your own branch only with `--force-with-lease`. Once the branch has been merged into `dev`, do not rebase or force-push it again: push fixes as new commits, so the later PR into `main` carries the same commits.
3. Open the PR into **`dev`**. Merge it with a **merge commit** (`gh pr merge <N> --merge`), not squash, and keep the branch.
4. The dev environment is redeployed from `dev`, then the tests and the demo path are run there.
5. If everything passes, open a second PR from the **same branch** into **`main`** and merge it with a merge commit. Delete the branch only after that.

If a change breaks `dev`, fix it with a new branch from `main` and the same flow. Do not patch `dev` directly.

Commits and PRs:
- Commit messages: imperative summary plus `(#<issue>)`.
- No AI attribution anywhere: no `Co-Authored-By` trailer for an AI and no "Generated with" line in PRs. The authors are the people on the team.
- Keep PRs small. The PR body contains:
  - `Closes #<N>`
  - what changed
  - **how it was verified, with the command output pasted**
  - risks and follow-ups
- Never use `--no-verify`. If a local git check blocks a commit or a push, fix the cause; if you can't, report it to your coordinator.
- Never:
  - push to `main` or `dev` directly (each machine installs a local pre-push check during setup; do not rely on it)
  - rewrite `main` or `dev` history
  - force-push or delete other people's branches
  - change git config (author identity)

## Definition of done
- Every acceptance criterion is met.
- Tests and the README run command pass, and their output is in the PR.
- CI is green on the PR.
- No secrets, no unrelated changes, and the branch still runs with one command.
- For the merge into `main`: the same change passed on the dev environment.

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
- End every report to a human or to your coordinator with a short **Still in progress** section: unfinished items, who has them, their state (in progress / waiting for review / waiting for merge / blocked by what), and decisions needed from a human.
