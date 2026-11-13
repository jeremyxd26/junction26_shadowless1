#!/usr/bin/env bash
# Prints the shared task board into the session context at start.
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" || exit 0
git fetch -q origin 2>/dev/null
echo "== $(git branch --show-current) | $(git status -sb | head -1)"
echo "== Open issues: #, assignees, labels, title"
gh issue list --state open --limit 60 --json number,title,assignees,labels \
  --jq '.[] | "#\(.number)  [\([.assignees[].login] | join(","))]  {\([.labels[].name] | join(","))}  \(.title)"' \
  2>/dev/null || echo "(gh unavailable)"
echo "== Open PRs"
gh pr list --state open --limit 30 2>/dev/null || true
exit 0
