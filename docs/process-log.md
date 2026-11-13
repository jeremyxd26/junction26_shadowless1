# Process log

How we built this during the hackathon. Times are Helsinki (UTC+2). Format: time · decision · why.

| When | Decision | Why |
|---|---|---|
| 2026-11-13 21:54 | Two long-lived branches `dev` and `main`, merge commits, no AI attribution (#7) | `dev` is tested on the dev environment before anything reaches the demo-ready `main`; merge commits keep the same commits in both, so the PR into `main` is exactly what was tested; the people on the team are the authors |
