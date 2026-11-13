# shadowless1 — Junction 2026

Work in progress.

## Run

The core service is a Python 3.11 FastAPI app. It reads its settings from environment variables, or from `.env` in the repository root (see `.env.example`). Without `DATABASE_URL` it still starts, and `/readyz` returns 503.

From the repository root, in a virtual environment:

```
pip install -r core/requirements.txt
uvicorn core.app.main:create_app --factory --port 8000   # start the core service
pytest core -q                                            # run the tests
```

`curl localhost:8000/healthz` returns `{"status":"ok","demo_today":"2026-09-30"}`. `curl localhost:8000/readyz` returns 200 when the database answers `SELECT 1`, and 503 with a short reason otherwise.

Settings:
- `DATABASE_URL`
- `DEMO_TODAY` (default `2026-09-30`)
- `GEMINI_API_KEY`: optional. Without it the coach answers from the rule planner and the templates.
- `GEMINI_MODEL`: leave it out of `.env` (see below).
- `CORS_ORIGINS`: comma-separated app origins. The default allows the local dev servers on ports 3000 and 5173.

The tests that need a database are skipped when `DATABASE_URL` is not set.

### Ask the coach: `POST /api/ask`

The answer pipeline is in `core/agent`: plan, run the tools, compose, validate, stream and audit (contract: `contracts/api.md` section 7; design: `docs/design/agent-core.md` sections 7 to 9).

The AI model is optional. Without `GEMINI_API_KEY`, the service runs a deterministic keyword model (`core/agent/rules.py`). It maps the partner's questions and spending questions to the registered tools and writes a template answer. Questions it cannot map get a clarifying question.

With `GEMINI_API_KEY` set, the service uses Gemini (`core/agent/gemini.py`; prompts in `core/agent/prompts/`) and still plans with the rules first:
- A question the rule planner recognises is planned without a model call. Gemini only writes the answer, so it costs one model call.
- Any other question goes to the Gemini planner, which uses function calling over the tool registry.
- Gemini writes the text with numbers as `{{nK}}` tokens. The validator checks the text, and a rejected draft is retried once, then replaced by the template.
- When Gemini fails (timeout, 429, 503, a refused key or model, an empty or cut response), or cannot be set up, the answer comes from the rule planner and the template. A 429, 401, 403 or 404 pauses model calls for 5 minutes.

The model id is pinned in code (`DEFAULT_MODEL` in `core/agent/gemini.py`, `gemini-3.8-flash`). Do not put a value for `GEMINI_MODEL` into `.env`: the local commit check treats every `.env` value of 12 or more characters as a secret and would block every commit that names the model. Override it only as a process variable for an experiment, for example `GEMINI_MODEL=gemini-3.1-pro-preview python ...`.

Model settings:
- `MODEL_DAILY_BUDGET`: requests to the Gemini API per UTC day. The default is 300. Requests are counted in `var/gemini-requests.jsonl`, so a restart keeps the count, and cache hits do not count. Past the budget, answers use the template. `0` turns the model off.
- `var/model-off`: while this file exists, no request is sent. It takes effect at once, without a restart or a redeploy.
- `GEMINI_FALLBACK_MODEL`: the model tried once when the main one stays overloaded (503 after two retries). The default is the other of flash and pro (pro is called on the `v1beta` API, the only one that serves it). `none` turns it off. A fallback the API refuses turns itself off.
- `GEMINI_CACHE`: `on` (default), `off` or `replay`. Responses are cached in `var/gemini-cache/`, keyed by the whole request, so a repeated question costs no request. `replay` never reaches the network.
- `GEMINI_PLANNER=model`: Gemini plans every question, not only the ones the rules do not recognise. Use it for eval runs of the planner.

```
curl -N -X POST localhost:8000/api/ask -H "Content-Type: application/json" -H "Accept: text/event-stream" \
  -d '{"customer_id":"CUST00860","conversation_id":null,"message":"How much did I spend on taxis last month?","language":"auto"}'
```

`Accept: application/json` returns one JSON object instead of the event stream. Every answer appends an audit record (question, tool calls, model views, validated text, outcome, tokens, timings; never transaction rows) to `var/audit/<date>.jsonl`.

Answer pipeline settings:
- `AUDIT_LOG_DIR`: where the audit records go. The default is `var/audit`.
- `AUDIT_API=1`: turns on `GET /api/audit/{answer_id}` for local eval runs. It is off by default, and must stay off on the public dev service: a record holds a customer's question and tool outputs.
- Rate limits on `POST /api/ask`, per process and per minute, answered with 429 before the stream opens. `0` turns a limit off, which is for local eval runs only.
  - `ASK_RATE_LIMIT_PER_MIN`: per client address, default 10.
  - `ASK_RATE_LIMIT_GLOBAL_PER_MIN`: all asks together, default 60.
  - `ASK_RATE_LIMIT_CUSTOMER_PER_MIN`: per customer, default 10.
- `TRUSTED_PROXIES`: comma-separated peers whose `X-Forwarded-For` is believed, default loopback only (the service listens on 127.0.0.1 behind Caddy). From any other peer the header is ignored.

To run the eval set against a local service with the keyword model:
```
AUDIT_API=1 ASK_RATE_LIMIT_PER_MIN=0 ASK_RATE_LIMIT_GLOBAL_PER_MIN=0 ASK_RATE_LIMIT_CUSTOMER_PER_MIN=0 uvicorn core.app.main:create_app --factory --port 8000
python core/eval/run.py --source api --base-url http://localhost:8000 --tag spending
```

To run it in process with Gemini, with a timing, token and cost table per answer:
```
python core/eval/run.py --source core.agent.gemini_eval:make_source --tag brief --persona CUST00860
GEMINI_PLANNER=model python core/eval/run.py --source core.agent.gemini_eval:make_source --tag red_team
python core/agent/gemini_eval.py "What if I cut it a little?"     # free-form questions
```
Every request counts against the team's daily model budget. Keep the cache on, and run each pass once. A repeated run is served from the cache. The offline tests replay recorded exchanges from `core/agent/tests/recordings/` and need no key and no network.

## Dev environment

The `dev` branch runs at **https://sentti.jeremyxd.dev** (`/healthz`, `/readyz`, later `/api/*`), on one Verda CPU instance in Finland at about 0.062 USD/h.

To deploy `origin/dev`, you need the instance SSH key at `~/.ssh/shadowless1_dev_ed25519`:

```
bash deploy/dev.sh
```

The instance pulls the code from GitHub itself, so push first. `docs/deploy.md` covers rollback, logs, settings, access and how to delete the instance (billing runs until the instance and its volume are deleted).

## Data

**The shared team database is already loaded. Do not run the loader against it.** The loader is only for an empty database: a fresh instance or a local one. On a database where `transactions` already has rows, it refuses to run. A re-run with `--force` drops and recreates every table, so the data is gone for everyone for several minutes.

The app runs on the synthetic S-Pankki dataset from the Junction 2026 "Personal Economic Trainer" challenge. The dataset is not stored in this repository.

To load it into an empty database:

1. Download it into `data/s-pankki` (the transactions file is stored with Git LFS):
   ```
   git lfs install
   git clone https://github.com/hackjunction/Junction-2026-S-pankki.git data/s-pankki
   ```
2. Set `DATABASE_URL` (PostgreSQL) in `.env`; see `.env.example`.
3. Load it:
   ```
   pip install -r core/requirements.txt
   python core/ingest/load.py data/s-pankki
   ```
   This creates the tables `transactions`, `customers`, `mortgage_applications` and `mortgage_events`, and prints the number of rows inserted into each.

### Metric marts

The peer benchmark and the grocery store index read three small precomputed tables. Build them once after every data load, and again whenever `DEMO_TODAY` changes. This is safe on the shared database: it never drops anything, it only creates `metric_customer_month`, `metric_peer_flags` and `metric_grocery_cells` if they are missing, and it rewrites their rows one batch at a time.

```
set -a && . ./.env && set +a      # build.py reads DATABASE_URL and DEMO_TODAY from the environment only
python core/marts/build.py
```

This is for Git Bash or another POSIX shell. In PowerShell, set `$env:DATABASE_URL` (and `$env:DEMO_TODAY` if it is not 2026-09-30) first, then run the same `python` line.

It runs 52 batches of 100 customers, printing one line per batch, and takes about 4 minutes. `--dry-run` lists the batches without touching the database, and `--from CUST01200` resumes after an interruption. Design: `docs/design/metrics.md`, section 8.

## Tests

From the repository root:
```
pip install -r core/requirements.txt
pytest core/tools -q
```
The pure-logic tests need no database. The database-backed tests run when `DATABASE_URL` is set (environment or `.env`) and are skipped otherwise. They only read one customer at a time and write evidence specs to the `coach_evidence` table, which they create if it is missing. Add `--durations=0` to see per-test times.

## Eval

The eval set checks that the coach states only correct numbers and refuses what it must refuse (rules R1 to R15 in `docs/design/research-bank-assistants.md`). The cases are in `core/eval/cases.yaml`: 49 cases for the four personas of `core/config/personas.yaml`, 64 questions in English and Finnish, every expected value with the SQL that produced it. The scripts read `DATABASE_URL` from the environment or from `.env`, and the peer cases need the metric marts above.

```
pip install -r core/requirements.txt
python core/eval/run.py --source reference      # answers from SQL; must pass 100%
python core/eval/expected.py --check            # the committed expected values equal a fresh regeneration
```

- `run.py` prints one line per question, a summary per tag, and exits 1 on any failure. Filters: `--tag red_team`, `--persona CUST00860`, `--case <id>`, `--lang fi`.
- `--source api --base-url http://localhost:8000` runs the same cases against the coach's `POST /api/ask` once it exists. `--source module:factory` plugs in any other answer source.
- After a metric change, `python core/eval/expected.py --write` regenerates the expected values (`--persona CUST00860` for one persona). Review the diff before committing it.
- `pytest core/eval -q` runs the regression tests of the checks: answers that lie must fail. No database is needed.

How numbers are checked (R1). The rule is an allowlist by subtraction in `core/answer_text.py`; the pipeline's output validator uses the same module.
0. Normalise the text with NFKC, so look-alike digits (superscript, circled, full-width) become plain digits.
1. Remove from the answer text the exact display string of every Number object the answer declares, where it stands alone: no €, % or dash next to it that belongs to another number (a declared count "1" never covers "1 €").
2. Remove every date expression that equals a date or period the tools returned. A date expression followed by € or % is not a date.
3. If any digit is left (an invented amount, an id, a number glued to letters, an amount after a dash), the answer fails.

Each declared Number object must also match an expected value: same unit, value within tolerance, same sign. A case may mark an expected value `required: false`: the answer may state it (for example the number of transactions next to a total) but need not. Money and percentages match only when the formatter shows them the same (45.915, shown as €45.92, is not 45.91), so a one-cent error fails; counts match exactly. A number from the question passes only as a user-input object with the question's own mark: the "20%" of a what-if question is a percent, never money.

- **Refusals and no-data answers** declare no numbers, so no digit is allowed in them. A refusal that quotes an amount from the question fails, and that is intended.
- **A source that does not report its tool calls or keys** fails those checks as "unverified". The summary counts them per tag.
- **Known limits**, not checked: numbers written as words ("twice", "kolme"), ordinals ("51st"), numerals in other scripts that NFKC does not map to digits, and wrong wording around a correct number ("per year" next to a monthly value, "rose" for a fall). In the pipeline, the unit and sign of the declared Number object guard the second.

## License

MIT
