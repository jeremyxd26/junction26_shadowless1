#!/usr/bin/env bash
# Copies the main checkout's .env into every git worktree of this repo.
# .env is gitignored; the main checkout's copy is the single source of truth.
# Runs at session start; run it by hand after editing .env.
common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
main="$(dirname "$common")"
[ -f "$main/.env" ] || exit 0
git worktree list --porcelain | sed -n 's/^worktree //p' | while IFS= read -r wt; do
  [ -d "$wt" ] || continue
  cmp -s "$main/.env" "$wt/.env" && continue
  cp "$main/.env" "$wt/.env" && echo "env synced -> $wt"
done
exit 0
