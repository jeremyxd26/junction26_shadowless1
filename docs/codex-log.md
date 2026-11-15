# How we used Codex

Codex (the OpenAI coding agent, CLI) was a second pair of eyes while we built Sentti at Junction 2026. It reviewed and tested; every fix went through our usual issues, reviews and PRs. This file is the one place in the repository where an AI tool is named on purpose (a team decision of Sat 14.11 01:57). Commits and PRs carry no AI signatures.

**Safety rules for every Codex run:**
- Read-only (`--sandbox read-only`), on a clean copy made with `git archive` or a separate clone, never in a working folder that holds `.env`.
- No keys, no real personal data: Sentti runs on the synthetic S-Pankki dataset and four demo personas.
- On the live stand, at most one question every 5 seconds, because the model has a daily budget.

## 1. Second reviewer on pull requests (from Sat 14.11 ~03:00)
Our reviewer step (`.claude/agents/reviewer.md`, step 3; set up in #222, PR #226) asks Codex for a second opinion on a PR's diff, on a clean copy with no `.env`. Two findings it added beyond the first review:
- **PR #199** (per-viewer answers to "Sentti asks"): flagged that after a viewer answered, the hero number and the chat could disagree.
- **PR #349** (explain a bill): an alphanumeric RF reference lost its leading zeros; fixed before the merge, so a valid reference is never rejected.

## 2. Product review against the challenge brief (Sun 15.11 ~01:00)
Codex walked the live product against S-Bank's asks for the challenge and listed findings by priority. Each became an issue, and all were deployed the same night:

| Finding | Issue | PR |
|---|---|---|
| P1: entry cards and a "More questions" sheet; a failed check digit on a bill stays visible; the overview's hierarchy | #809 | #810 |
| P2: undo for "Not sure" and "Change answer"; one "How Sentti works" element; the comparison group next to the result | #812 | #813 |
| P3: a one-time hint for the header icons and the paperclip; the Sentti label only on the first answer | #815 | #816 |
| A stated constraint was lost ("if I cannot reduce rent…") | #804 | #817 |
| A period outside the data got unrelated totals | #805 | #817 |
| "Should I borrow €500 for a holiday?" got the credit refusal instead of the budget side | #806 | #818 |

## 3. Dataset analysis (Sun 15.11 morning)
Codex read the organisers' CSV files directly and wrote an analysis and a data handbook for the agent: the row counts (3,626,755 transactions of 5,100 customers, the same as our database), medians per basket by age band, correlations between customers (age and money coming in: Spearman 0.47, moderate), and traps for an analytics agent (investment sweeps are not spending, income series kept apart, a "today" fixed to the data's last day, a minimum group size, zero bases in percentages).
- We audited Sentti against the traps: six passed, one Finnish wording failed (an average purchase called "keskihinta", an average price), fixed in #867 (PR #868).
- The analysis became the fourth Learn topic, "Compare wisely" (#869): a median, not an average; a link is not a cause; spending is not moving money to savings.

## 4. Conversation test on the live stand (Sun 15.11 morning)
Codex ran a scripted conversation of 30 checks against https://sentti.jeremyxd.dev in English and colloquial Finnish, across the four personas, writing down every answer word for word. It looked for numbers pushed where none were asked, feedback not understood, repetition and mixed languages; 14 of 30 checks failed. The fixes:
- **#920** (PR #921): confusion replies ("wait what", "täh"), "say it more simply" refers to the last answer, a kind line for feelings ("I'm tired"), a greeting is never read as a person's name. Regression tests: `core/agent/tests/test_agent_codex_fixes.py`.
- **#919** (PR #932): "why?" after a tips answer explains those tips, not a general paragraph.
- **PR #923**: concept and judgement questions ("what is X", "is it bad to…", "mitä on", "onko paha…") get an answer in words with a source, not a personal number card.
- The 30 checks are part of the acceptance probes for the agent mode (#937).

## What Codex did not do
It made no commits, never saw `.env` or any key, and had no access to the shared database or the dev host.
