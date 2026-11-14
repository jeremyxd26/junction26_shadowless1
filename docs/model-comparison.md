# Model comparison: composer and planner (#169)

Measured on 2026-11-14. The question was whether a faster model can write the coach's answers and plan its tool calls, and whether an open model (NVIDIA Nemotron) could replace Gemini.

**Verdict:**
- The composer moves to `gemini-3.5-flash-lite` (thinking `minimal`). It passes the number check as often as `gemini-3.8-flash` does, at under a third of the latency.
- Nemotron is below Flash-Lite on the number check and on latency, so no GPU endpoint is needed for the composer.
- **The planner on round 1:** on 60 questions the rules do not answer, Flash-Lite plans as accurately as `gemini-3.8-flash` or better, 3.5 times faster, without Flash's 8-second server errors.
  - It can become the planner only after an adapter fix. After this measurement, a diagnostic run found that with Flash-Lite as planner every round-2 planner request fails with HTTP 400 ("Role 'tool' is not supported"): the adapter sends the function-response turn with role `tool`, which `gemini-3.8-flash` tolerates. The one-line fix is in review.
  - On the dev environment, the composer runs on Flash-Lite now. The planner stays on Flash until that fix is deployed.
- **Against the issue's threshold** (the number check and the right tool at no less than 90 % of Flash's results, latency at no more than 1.5 times Flash's), Flash-Lite passes:
  - first drafts 48 against 48, and right plans 38 against 34;
  - latency 0.29 times Flash's as composer and 0.28 times as planner.
- Nemotron fails the threshold on the number check: 28 first drafts against Flash's 48 (58 %), even though its latency would pass (0.46 times).

All numbers come from the service's own pipeline: the prompts, the validator, the template fallback and the tools of dev. The scripts are `core/eval/model_compare.py` (composer) and `core/eval/planner_compare.py` (planner). Every model went through the adapter's `GeminiClient`: its response cache (a rerun sends nothing), its request ledger (a hard cap per run) and its pauses after an error. The runs used `SPIKE_REVIEWS=off` (the published numbers), one request at a time.

## Composer: the same 49 answers

The rules plan; the model writes. The answers are every answered case of `core/eval/cases.yaml` (36 English, 13 Finnish), on dev cc69d4b.

| Composer | Validator: first draft / retry / template | Composer call: median / p90 / max | All expected numbers in the answer | Requests | Cost per answer |
|---|---|---|---|---|---|
| `gemini-3.8-flash`, thinking `low` | 48 / 1 / 0 | 2.75 / 3.78 / 5.20 s | 37 of 49 | 50 | $0.0027 |
| `gemini-3.5-flash-lite`, thinking `minimal` | **48 / 1 / 0** | **0.79 / 0.97 / 1.30 s** | 33 of 49 | 49 (+2 probes) | ≈ $0.0012 |
| `nvidia/nemotron-3.5-super-vl-120b-a12b`, reasoning off | 28 / 10 / 11 | 1.26 / 1.75 / 2.27 s | 25 of 49 | 69 (+1 probe), NVIDIA Build | — |

- **The numbers stay correct.** After the validator no model put a wrong or invented number into an answer; a rejected draft is retried once, then answered by the template.
- **First-draft violations:**
  - Flash: one "promise".
  - Flash-Lite: one unknown number id, in a Finnish draft.
  - Nemotron: 21 of 49 first drafts rejected. A draft can have several problems: 18 had digits that do not come from a tool, 9 had two number tokens side by side, 1 a malformed token, 1 a date that was not returned, and 1 a cited list that differs from the tokens.
- **Every answer reached its model.** In a first Nemotron run, the ledger cap (60) was reached before the last 6 answers, and the pipeline answered those from the template without a model call. They were then run with the cap at 72, and every earlier response came from the cache, so the line above covers all 49. Its 70 composer calls are the 69 requests plus one cache hit, the probe's response for the same answer.
- **Nemotron's settings:**
  - reasoning off: a `/no_think` system line and `chat_template_kwargs.enable_thinking=false`;
  - the composer's JSON Schema as `response_format` (`json_schema`).
  - The structured answer arrives in one piece, so its first token comes at about the total time.
  - Model id from the NVIDIA NIM documentation, checked 2026-11-14.
- **Thinking.** `gemini-3.5-flash-lite` used no thinking tokens. `gemini-3.8-flash` rejects `minimal` and runs at `low`, so its latency is mostly thinking.
  - These scripts measure the total time of a call, not the first token.
  - Renat measured the first token separately, on his machine, with one composer prompt and two runs each: 5.85 s for `gemini-3.8-flash` at `low` and 0.48 s for Flash-Lite.
- **Price.** Flash-Lite costs $0.30 per 1M input tokens and $2.50 per 1M output tokens. The adapter's price table has no row for it yet.

**Completeness by question type.** Each cell counts four kinds of answer:
1. every expected number is in the answer;
2. the answer leaves one out;
3. the answer is unverifiable with this eval source, which does not report the tools' results;
4. another eval check failed.

| Question type | Answers | Flash-Lite | Flash | Nemotron |
|---|---|---|---|---|
| spending | 13 | 13 / 0 / 0 / 0 | 13 / 0 / 0 / 0 | 13 / 0 / 0 / 0 |
| where money went | 6 | 6 / 0 / 0 / 0 | 6 / 0 / 0 / 0 | 5 / 0 / 1 / 0 |
| safe to spend | 6 | 5 / 0 / 1 / 0 | 6 / 0 / 0 / 0 | 5 / 0 / 1 / 0 |
| spender type | 6 | 0 / 6 / 0 / 0 | 0 / 6 / 0 / 0 | 0 / 6 / 0 / 0 |
| what-if | 8 | 4 / 3 / 0 / 1 | 7 / 0 / 0 / 1 | 0 / 2 / 6 / 0 |
| bills | 5 | 2 / 0 / 3 / 0 | 2 / 0 / 3 / 0 | 0 / 0 / 5 / 0 |
| comparison | 3 | 3 / 0 / 0 / 0 | 3 / 0 / 0 / 0 | 2 / 1 / 0 / 0 |
| save more | 2 | 0 / 2 / 0 / 0 | 0 / 2 / 0 / 0 | 0 / 2 / 0 / 0 |
| **all** | **49** | **33** / 11 / 4 / 1 | **37** / 8 / 3 / 1 | **25** / 11 / 13 / 0 |

- **The "other" failure of Flash-Lite and Flash** is the same answer, `eetu-cut-home-tech-with-caveat`. The eval's R1 check finds "50 %" declared as user input that the question does not state. That is the pipeline's what-if argument, not the composer.

- **The spender-type answer** leaves out the peer median, the peer percentile and the group size with every model, every time. The cause is therefore the prompt or the data view, not the model (#288).
- **Flash-Lite's one real gap against Flash:** it leaves out the dining baseline in the what-if answer three times.

## Planner: 60 questions the rules do not answer

Round 1 of the service's planner, one request per question: the planner prompt and tool declarations of dev d72aa38, no history. The questions are:
- **39 phrasings** of the four brief questions that the rules do not recognise: the QA table on #340, English and Finnish, typos included, 9 of them typed without ä and ö.
- **The eval's 18 red-team questions** (refusals).
- **Three live problem questions,** with keys written by hand:
  - "what was that €1,080?": a clarifying question or spending;
  - "what if I took 10% fewer taxis?": the what-if;
  - "is it ok if i spend a bit this week, what's my limit?": safe to spend.

A plan is right when it calls the intent's tool: baskets; the spender profile; safe to spend; safe to save or baskets. A red-team plan is right when it declines.

| Planner | Unrecognised phrasings right | Red team right | Live right | Call: median / p90 / max | Server errors (5xx) | Requests |
|---|---|---|---|---|---|---|
| `gemini-3.8-flash`, thinking `low` | 34 of 39 | 17 of 18 | 2 of 3 | 2.15 / 3.13 / 5.88 s | **6 of 60**, each after 8.1–8.6 s | 61 |
| `gemini-3.5-flash-lite`, thinking `minimal` | **38 of 39** | **18 of 18** | **3 of 3** | **0.61 / 0.77 / 1.14 s** | 0 | 60 |
| Nemotron | not measured (it needs a tool-calling transport; its composer result already answers the question) | | | | | |

- **Flash's hang.** Six questions ended after about 8 s in a 5xx, and the adapter then paused for 30 s:
  - "Mihin käytän eniten rahaa?";
  - "Millainen rahankäyttäjä olen?" (typed without ä);
  - "Miten saisin rahaa säästöön?";
  - "describe my spending habits";
  - the admin-mode injection;
  - "what was that €1,080?".
  - On the service this is the 8-second hang and 5xx seen live. The latency columns count only the calls that answered.
- **What each planner missed:**
  - Flash missed 5 of the 39 unrecognised phrasings: 4 server errors and 1 wrong plan. Its red-team miss and its live miss are both server errors.
  - Flash-Lite's single miss is that same wrong plan, "what am I spending the most on?". Both models answer it with spending by category for last month instead of the baskets, which is a reasonable reading.
- **Both models build the taxi what-if wrongly:** `{"kind": "mcc", "value": "taxi"}` instead of a 4-digit code, so the service rejects the arguments. The cause is the declaration or the prompt, not the model.

**Verdict:** I would run the planner on Flash-Lite once the adapter's round-2 fix is deployed (see the verdict at the top). It is at least as accurate here (38 of 39 phrasings and every refusal, against 34 and 17 of 18), 3.5 times faster, and it never hit Flash's 8-second 5xx.

## Limits

- **Small samples, one run each.**
  - The composer was measured on 49 answers and the planner on 60 questions, each once per model.
  - Differences of one or two answers are within what a second run could change. The latency is from one run per call, at the time of day of the run.
- **First token.** These scripts measure the total time of a model call. The first token was not measured for Gemini (the SDK path does not stream). For Nemotron it is measured, and it equals the total, because its structured answer arrives in one piece.
- **Completeness is a stricter check than the validator.** An answer that leaves out a supporting number is still a correct answer. The comparison column is there to show prompt gaps, not wrong numbers.
- **The planner was measured on round 1 only:** the first plan, without the tools' results.
  - That is why these runs could not see the round-2 failure on Flash-Lite, the HTTP 400 for the role `tool` of the function-response turn, found afterwards.
  - Round 2 needs a measurement of its own once the adapter fix is in.

## How to repeat it

Composer, one model per run (the case ids are the answered cases of the eval set):

```
SPIKE_REVIEWS=off M169_THINKING=minimal GEMINI_MODEL=gemini-3.5-flash-lite GEMINI_FALLBACK_MODEL=none \
MODEL_DAILY_BUDGET=80 M169_OUT=var/m169/flash-lite.jsonl \
python core/eval/run.py --source core.eval.model_compare:make_source --case <id> ...
SPIKE_REVIEWS=off NVIDIA_CAP=72 M169_OUT=var/m169/nemotron.jsonl \
python core/eval/run.py --source core.eval.model_compare:make_nemotron_source --case <id> ...
python core/eval/model_compare.py var/m169/flash-lite.jsonl
```

Planner:

```
SPIKE_REVIEWS=off GEMINI_MODEL=gemini-3.5-flash-lite GEMINI_FALLBACK_MODEL=none python core/eval/planner_compare.py \
    --thinking minimal --ledger var/m169/planner-lite-requests.jsonl --cap 61 --out var/m169/planner-lite.jsonl
python core/eval/planner_compare.py --summary var/m169/planner-lite.jsonl
```

Keys come only from the environment or `.env` (`GEMINI_API_KEY`, `NVIDIA_API_KEY`) and are never printed or stored. Responses are cached under `var/`, so a rerun costs no requests.
