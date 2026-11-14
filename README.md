# shadowless1 — Junction 2026

[![CI](https://github.com/jeremyxd26/junction26_shadowless1/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jeremyxd26/junction26_shadowless1/actions/workflows/ci.yml)

Work in progress.

How S-mobiili embeds Sentti, an embeddable web module (WebView): [docs/integration.md](docs/integration.md).

## Run

The core service is a Python 3.11 FastAPI app. It reads its settings from environment variables, or from `.env` in the repository root (see `.env.example`). Without `DATABASE_URL` it still starts, and `/readyz` returns 503.

From the repository root, in a virtual environment:

```
pip install -r core/requirements.txt
uvicorn core.app.main:create_app --factory --port 8000   # start the core service
pytest core -q                                            # run the tests
```

`core/requirements.txt` pins every package to an exact version. To change one, follow the steps in its header.

`curl localhost:8000/healthz` returns `{"status":"ok","demo_today":"2026-09-30"}`. `curl localhost:8000/readyz` returns 200 when the database answers `SELECT 1`, and 503 with a short reason otherwise.

Settings:
- `DATABASE_URL`
- `DEMO_TODAY` (default `2026-09-30`)
- `DEMO_CUSTOMERS`: `personas` (default) serves only the demo personas of `core/config/personas.yaml`; `all` serves every customer of the data, for local eval runs only.
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `CORS_ORIGINS`: comma-separated app origins. The default allows the local dev servers on ports 3000 and 5173.
- `DB_POOL_MAX` (default `10`, 1 to 20): the most database connections the service's pool opens. Every local run and every database-backed test that starts the service opens up to this many.
- `API_DOCS` (default off): `1` serves the interactive API docs (`/docs`, `/redoc`, `/openapi.json`), for local development only.
- `SPIKE_REVIEWS` (default on): the coach asks about one spending spike, and the answer changes the numbers. Set it to `off` to serve the published numbers with no review: no label is read and no review is created.

The tests that need a database are skipped when `DATABASE_URL` is not set.

CI (`.github/workflows/ci.yml`) runs on every pull request and every push to `dev` and `main`: the tests without a database, the eval set and red-team regressions (no model calls), `ruff check .` (`pip install -r requirements-dev.txt`) and a gitleaks scan of the whole history (`.gitleaks.toml`). It uses no secrets.

### Ask the coach: `POST /api/ask`

The answer pipeline is in `core/agent`: plan, run the tools, compose, validate, stream and audit (contract: `contracts/api.md` section 7; design: `docs/design/agent-core.md` sections 7 to 9). Until the Gemini adapter is plugged in, the service runs a deterministic keyword model (`core/agent/rules.py`). It maps the partner's questions and spending questions to the registered tools and writes a template answer. Questions it cannot map get a clarifying question.

```
curl -N -X POST localhost:8000/api/ask -H "Content-Type: application/json" -H "Accept: text/event-stream" \
  -d '{"customer_id":"CUST00860","conversation_id":null,"message":"How much did I spend on taxis last month?","language":"auto"}'
```

`Accept: application/json` returns one JSON object instead of the event stream. Every answer appends an audit record (question, tool calls, model views, validated text, outcome, tokens, timings; never transaction rows) to `var/audit/<date>.jsonl`.

Answer pipeline settings:
- `AUDIT_LOG_DIR`: where the audit records go. The default is `var/audit`.
- `AUDIT_API=1`: turns on `GET /api/audit/{answer_id}` for local eval runs. It is read when the service starts. It is off by default, and must stay off on the public dev service: a record holds a customer's question and tool outputs. When it is off, the route does not exist, and the path answers like any unknown path.
- Rate limits on `POST /api/ask`, per process and per minute, answered with 429 before the stream opens. `0` turns a limit off, which is for local eval runs only.
  - `ASK_RATE_LIMIT_PER_MIN`: per client address, default 10.
  - `ASK_RATE_LIMIT_GLOBAL_PER_MIN`: all asks together, default 60.
  - `ASK_RATE_LIMIT_CUSTOMER_PER_MIN`: per client address and customer, default 10. One address that uses up its window for a persona never blocks that persona for other visitors.
- `TRUSTED_PROXIES`: comma-separated peers whose `X-Forwarded-For` is believed, default loopback only. From any other peer the header is ignored. In the image, uvicorn runs with `--proxy-headers` behind Caddy, which replaces `X-Forwarded-For`, so uvicorn already reports the client's address.

To run the eval set against a local service with the keyword model:
```
AUDIT_API=1 ASK_RATE_LIMIT_PER_MIN=0 ASK_RATE_LIMIT_GLOBAL_PER_MIN=0 ASK_RATE_LIMIT_CUSTOMER_PER_MIN=0 uvicorn core.app.main:create_app --factory --port 8000
python core/eval/run.py --source api --base-url http://localhost:8000 --tag spending
```

## Dev environment

The `dev` branch runs at **https://sentti.jeremyxd.dev** (`/healthz`, `/readyz`, later `/api/*`), on one Verda CPU instance in Finland at about 0.062 USD/h.

To deploy `origin/dev`, you need the instance SSH key at `~/.ssh/shadowless1_dev_ed25519`:

```
bash deploy/dev.sh
```

The instance pulls the code from GitHub itself, so push first. `docs/deploy.md` covers rollback, logs, settings, access and how to delete the instance (billing runs until the instance and its volume are deleted).

## Spike reviews and the demo reset

The first `GET /api/overview/{customer_id}` of a customer with a qualifying spike creates a pending review in the `spike_reviews` table. The service creates that table if it is missing. While the review is pending, the purchase is "Waiting for your answer" (`unclassified`). `POST /api/baskets/label` stores the answer. Design: `docs/design/agent-core.md` section 7.8; contract: `contracts/api.md` sections 6 and 10.

The answers live only in `spike_reviews`, on the shared database that the dev environment also uses. To start the demo again, delete the personas' reviews from any checkout whose `.env` points at that database. The script refuses to run without explicit customer ids:

```
python core/scripts/reset_reviews.py CUST00860                                  # Sanna
python core/scripts/reset_reviews.py CUST00860 CUST00493 CUST00349 CUST00849    # the four personas
python core/scripts/reset_reviews.py --dry-run CUST00860                        # show, delete nothing
```

Reference answers, such as the eval set's expected values, are the state with no review. Before you compare a running service with them, either set `SPIKE_REVIEWS=off` on that service or reset the personas first.

**Run the reset right before the demo.** A review closes 7 real days after its first serve, while the demo date (`DEMO_TODAY`) stands still. After that, a persona has no card until `reset_reviews.py` is run. No new review is created while the customer's latest one can still be answered or undone, so a customer has at most one open review per 7 days.

The tests run with `SPIKE_REVIEWS=off`, so they see the published numbers whatever the demo answered. The spike-review tests switch it on inside a transaction that is rolled back. They never commit a review, a label or the `spike_reviews` table itself.

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
- The expected values are the state with no spike review. Before an `--source api` run, set `SPIKE_REVIEWS=off` on that service or reset the personas (see "Spike reviews and the demo reset"). The `reference` source runs the metric SQL without labels, so it is not affected.
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
