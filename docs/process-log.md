# Process log

How we built this during the hackathon. Times are Helsinki (UTC+2). Format: time · decision · why.

| When | Decision | Why |
|---|---|---|
| 2026-11-13 21:54 | Two long-lived branches `dev` and `main`, merge commits, no AI attribution (#7) | `dev` is tested on the dev environment before anything reaches the demo-ready `main`; merge commits keep the same commits in both, so the PR into `main` is exactly what was tested; the people on the team are the authors |
| 2026-11-13 22:03 | Keep the attribution trailer on the already pushed commit 0ec62e7; no history rewrite; attribution is off for new commits | Rewriting pushed history to drop a trailer is not worth the risk; owner decision |
