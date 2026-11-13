# Sentti, the coach: agent core design

**Issues:** #5, #33, #34 · **Status:** draft for review · **API contract:** [contracts/api.md](../../contracts/api.md)

The coach is called **Sentti** (product decision, issue #34). It introduces itself by that name, in the AI disclosure ("Sentti is an AI assistant …") and in its answers. In this document "the coach" is the generic word for the same assistant.

**Related:**
- `docs/design/metrics.md` (issue #6): metric formulas and method ids. Not on `main` yet.
- `docs/design/research-bank-assistants.md` (issue #3): rules R1 to R15. Draft; the rule ids are stable.

This document defines how the coach answers a question: which tools exist, what the AI model may and may not do, how every number is traced to its evidence, and what happens when something fails. It defines no formulas. Where a number comes from a formula, the design names the metric, and `metrics.md` defines it. Rule ids such as **(R1)** point to the research rules a choice implements.

## Contents

1. [Summary](#1-summary)
2. [Context and constraints](#2-context-and-constraints)
3. [Architecture](#3-architecture)
4. [Data access and the privacy boundary](#4-data-access-and-the-privacy-boundary)
5. [Numbers and evidence](#5-numbers-and-evidence)
6. [Tool registry](#6-tool-registry)
7. [Conversation flow](#7-conversation-flow)
8. [Guardrails](#8-guardrails)
9. [Audit log and eval set](#9-audit-log-and-eval-set)
10. [Latency budget](#10-latency-budget)
11. [Failure modes](#11-failure-modes)
12. [Gemini integration notes](#12-gemini-integration-notes)
13. [Open questions](#13-open-questions)
14. [Coverage of the issue and of the research rules](#14-coverage-of-the-issue-and-of-the-research-rules)

---

## 1. Summary

- **Tools compute, the model explains.** A fixed registry of deterministic, read-only tools on top of a metrics layer. There is no text-to-SQL, and the model never writes a query.
- **Every number is an object with evidence.** Numbers travel as `{value, unit, period, method, evidence_ref}`, and any number on screen can be opened to the transactions or inputs behind it **(R1, R2)**.
- **The model never types a digit.** It cites numbers as tokens such as `{{n3}}`, and the server swaps in the formatted value. A validator rejects any other digit, so an invented number cannot reach the user **(R1)**.
- **Two model steps:**
  1. A *planner* uses function calling to pick tools.
  2. A *composer* writes the answer as schema-checked JSON. Invalid output is retried once, then replaced by a template answer built from the tool results **(R12)**.
- **The server owns the context.** The customer and "today" (`DEMO_TODAY`) come from the server and are never tool arguments **(R4, R5)**. Raw transaction rows, merchant ids and balance series never reach the model **(R3)**.
- **The overview and the what-if screen use no AI model.** They are deterministic and fast. The model is used only where language helps: understanding the question and explaining the answer.

## 2. Context and constraints

| Item | Fact |
|---|---|
| Data | Tables `transactions`, `customers`, `mortgage_applications`, `mortgage_events` (schema in `core/ingest/schema.sql`). 3.6M transactions, 5,100 customers, 2024-10-01 to 2026-09-30, 15 categories, 36 MCC codes, anonymised merchants. |
| Transfers | An empty or `.` `merchant_id` or `mcc` means a non-card transfer. `transaction_type` is the economic purpose of the transaction (partner data dictionary). |
| Today | `DEMO_TODAY`, default `2026-09-30`. Tools see nothing after it. |
| Database | 2 GB RAM, 25 connections. One full-table aggregate restarted it once, so heavy aggregates are precomputed in batches by customer range with a `statement_timeout`. Pools stay tiny. |
| LLM | Gemini through the `google-genai` Python SDK (section 12). |
| Users | Mobile-first web app, English and Finnish. |
| Intents | The partner's four questions are the canonical intents: "Where did my money go?", "What kind of spender am I?", "What can I safely spend this week?" and "How could I save more?" |

## 3. Architecture

```text
 app (mobile web)
   │  HTTPS: JSON, and server-sent events for /api/ask
   ▼
 core API ─────────────────────────────────────────────────────────────────────
   │ GET  /api/personas, /api/overview/{id} ──► Metrics layer ──┐
   │ POST /api/whatif ────────────────────────► Metrics layer   │
   │ GET  /api/evidence/{ref} ───────────────► Evidence store   │
   │ POST /api/baskets/label (app only) ─────► Review table     │
   │ POST /api/ask ──► Coach orchestrator                       │
   │                     1 Input guard                          │
   │                     2 Planner  ◄─► Gemini (function calls) │
   │                     3 Tool registry ──► Metrics layer ─────┤
   │                     4 Card builder (deterministic)         │
   │                     5 Composer ◄─► Gemini (JSON schema)    │
   │                     6 Output validator ─► template fallback│
   │                     7 Audit log                            │
   ▼                                                            ▼
                                      PostgreSQL: precomputed tables + per-customer indexed reads
```

| Component | Responsibility | Owner |
|---|---|---|
| Metrics layer | Pure functions and precomputed tables that produce Number objects. Formulas, method ids and SQL come from #6. | core (r-w2 defines it) |
| Tool registry | Typed wrappers that the model can call (section 6). Each tool calls the metrics layer and returns a typed result, a card and a compact view for the model. | core |
| Evidence store | Saves the recipe of each number and resolves `GET /api/evidence/{ref}` (section 5). | core |
| Coach orchestrator | Runs one answer: guard, planner loop, tools, cards, composer, validator, audit. | core |
| Card builder | Turns tool results into cards. The model never writes cards. | core |
| Output validator | Checks the composer's JSON (section 7.4). | core |
| Audit log | One record per answer (section 9). | core |

## 4. Data access and the privacy boundary

**What the AI model sees and never sees (R3):**

| The model sees | The model never sees |
|---|---|
| The user's question, wrapped as data | Transaction rows, one by one |
| The previous questions and answers of this conversation, with numbers masked | Merchant ids. It sees aliases such as `store_a` with the digit-free label the app also shows, such as "Grocery store A". |
| A compact view of each tool result: number ids, values, units, labels, period labels and flags | `balance_after` series, timestamps, account ids |
| Category, basket and profile labels | `customer_id`, postal code, exact age. It sees only coarse peer-group labels such as "Age 25-34, postal area 005". |
| The date `as_of` | Evidence refs and the evidence store |

**Context bound by the server:**
- **Customer (R4):** every tool receives a context `{customer_id, as_of, language}` from the server. No tool has a `customer_id` argument, so no model output can select another customer. In demo mode the customer is the persona sent by the app; in production it comes from the bank session.
- **Time (R5):** `as_of` = `DEMO_TODAY`. Tools clamp every period to `[2024-10-01, as_of]` and return the resolved dates, which the answer then names. Dates after `as_of` appear only as predictions, such as a bill's `next_expected`.
- **Read-only (R6):** tools only read and simulate. The registry contains nothing that moves money, changes settings or contacts anyone.

**Database use:**
- **Request path:** the API holds a pool of at most 3 connections, uses `SET statement_timeout = '5s'`, and makes per-customer reads through the existing indexes (`tx_customer_time`, `tx_customer_category`, `tx_customer_mcc`). One customer has about 700 rows, so these reads are cheap.
- **Batch path:** anything that crosses customers runs as a batch job by customer range with `statement_timeout = '60s'`. That covers peer distributions, the store price index and the per-customer snapshot behind `/api/overview`. It writes precomputed tables. #6 owns that SQL. **No request ever aggregates the whole `transactions` table.**

## 5. Numbers and evidence

### 5.1 The Number object

Every number is `{value, unit, period, method, evidence_ref}` plus a localised `label` and `display` (contract, section 2.1).
- `method` is `<metric>.<output column>@<version>` and points to the exact output in `metrics.md` and `core/metrics/` (section 6.2).
- Spending is positive. Changes are signed.
- `evidence_ref` is `null` only for values the user typed in (`user_input@1`).

Inside one answer the orchestrator gives each number an id (`n1`, `n2`, …). The model and the text tokens use the id, and the server keeps the map from id to full Number object.

### 5.2 Evidence (R2)

When a tool produces a number, it also writes an **evidence spec**: the recipe needed to rebuild the number.

| `kind` | Spec content | What `GET /api/evidence/{ref}` returns |
|---|---|---|
| `transactions` | Customer, filter (categories, baskets, MCC groups, merchant), period, method | The transaction rows (paginated), `row_count` and `reconciles`: the rows recomputed with `method` equal `value` |
| `composite` | The method and the refs of the input numbers | `parts`: the input Number objects, each with its own ref, so the user can drill down |
| `peer_aggregate` | Peer group, metric, period | Group statistics only: median, quartiles, group size. Never other customers' rows. |
| `store_index` | Store, method, window | The index inputs at store level |

Values the user typed in (`user_input@1`) carry `evidence_ref: null` and have no evidence spec.

- **Ref:** `ev_` plus 12 lowercase letters and digits taken from `sha256(canonical JSON of the spec)`. The spec includes the method, so **one ref backs exactly one number**. The same number for the same customer and `as_of` always gets the same ref, even when it is shown in several places, so refs are stable across restarts and repeated questions. The spec also includes the customer's spike labels in effect (section 7.8). After a label the affected numbers get new refs, and old refs keep resolving to the numbers as they were.
- **Storage:** specs live in a small table `coach_evidence(ref primary key, customer_id, spec jsonb, created_at)`. Writes are idempotent.
- **Resolution:** `GET /api/evidence/{ref}` loads the spec, checks that it belongs to the customer in the request (403 otherwise), and re-runs the spec query. If the rows do not reconcile with `value`, it returns `reconciles: false` and logs an error. An eval check fails on that (R2).
- **Privacy:** for `peer_aggregate` the inputs are other customers, so the app gets the distribution and the recompute check runs inside the eval job only.
- **No model access (R3):** the evidence endpoint is for the app. Evidence is never part of a model prompt.

## 6. Tool registry

### 6.1 Conventions

- **Shape:** each tool is `tool(ctx, args) -> ToolResult`. `ctx` is server-bound (section 4). `args` is a Pydantic model. Its JSON Schema is sent to Gemini as `parameters_json_schema`, and the same model validates the arguments the model returns. Invalid arguments never reach the metrics layer.
- **No free text:** no argument is free text that reaches a query. All arguments are enums, dates, numbers, bill ids or merchant aliases. A prompt injection therefore has no path to SQL (R11).
- **`ToolResult`:**
  - `data`: typed and listed below.
  - `card`: Card or null.
  - `notes`: caveats, for example "no transactions in this period".
  - `evidence`: the refs written.
  - `model_view`: the compact projection the model sees (section 6.4).
- **Results are deterministic and cacheable** by `(customer_id, tool, args, as_of, label set hash)`. The label set is the customer's spike labels (section 7.8), so a new label invalidates exactly that customer's cached results.

Shared types:

```text
Category    = "Groceries" | "Restaurants" | "Transportation" | "Utilities" | "Entertainment"
            | "Health" | "Home & Tech" | "Housing" | "Lifestyle" | "Travel"
            | "Salary" | "Other Income" | "Invest Withdraw" | "Invest Deposit" | "Salary Sweep"
Basket      = "regular_essentials" | "unexpected_necessities" | "everyday_spending"
MccGroup    = "groceries" | "restaurants" | "taxi" | "public_transport" | "fuel" | "parking"
            | "health" | "electronics_home"          # code lists live in the metrics config (#6)
PeriodArg   = { preset: "this_week" | "last_week" | "this_month" | "last_month" | "last_3_months"
                      | "last_6_months" | "last_12_months" | "year_to_date" | "custom",
                start?: date, end?: date }           # start/end only with "custom"
                # last_6_months = the last 6 complete calendar months (metrics.md section 0)
Period      = { start: date, end: date, label: string }   # resolved and clamped (R5)
Filter      = { categories?: Category[], baskets?: Basket[], mcc_groups?: MccGroup[],
                merchant?: MerchantAlias }
MerchantAlias = "store_a" | "store_b" | ...          # mapped to merchant ids on the server (R3)
                # Label: "<kind> <letter>", for example "Grocery store A", without digits and stable per
                # customer (letters by spend rank up to as_of). Cards, evidence and answers all use it.
Number, Comparison, Card = see contracts/api.md
```

The rules that turn a preset into dates (for example where a week starts) are defined in `metrics.md`. Tools always return the resolved `Period`.

### 6.2 Data tools

| Tool | Answers | Card | Main method ids |
|---|---|---|---|
| `get_spending` | Spending or income by filter and period, optionally grouped and compared | `metric` (no grouping) or `breakdown` | `spending.total`, `spending.change`, `spending.change_pct`, `spending.share_pct`, `spending.n_tx` (plain sums and counts over the filter, defined here) |
| `get_basket_breakdown` | Split into the three baskets, monthly average over the window | `breakdown` (`stacked_bar`) | `baskets.month_avg_eur`, `baskets.share_pct`, `spender_profile.spend_month_eur` |
| `get_recurring_bills` | Recurring bills and income cadence, bills due before payday | `bills` | `recurring.typical_month_eur`, `safe_to_spend.bills_due_eur` (the total), `safe_to_spend.bill_due_eur` (one bill's term of it) |
| `get_safe_to_spend` | Safe to spend in the next 7 days | `metric` with `components`, `estimate` set | `safe_to_spend.safe_to_spend_7d_eur`, `.free_until_payday_eur`, `.balance_limit_7d_eur`, `.budget_limit_7d_eur`, `.balance_eur`, `.bills_due_eur`, `.essentials_reserve_eur`, `.irregular_reserve_eur`, `.cushion_eur` |
| `run_what_if` | Savings from cutting a selection by a percentage | `whatif` (`estimate` set) | `what_if.baseline_month_eur`, `.saving_month_eur`, `.saving_week_eur`, `.saving_year_eur`, `.one_off_excluded_eur`, `.regular_excluded_eur` |
| `get_spender_profile` | "What kind of spender am I?" | `profile` | `spender_profile.<feature column>`, for example `spender_profile.keep_rate_pct` |
| `get_peer_benchmark` | Comparison with people of the same age band and area | `peer` (`estimate` set) | `peer_benchmark.you_month_eur`, `.peer_median_month_eur`, `.peer_p25_month_eur`, `.peer_p75_month_eur`, `.percentile`, `.vs_median_pct`, `.peer_n` |
| `compare_store_prices` | Grocery store price levels, and whether switching would save anything | `stores` (`estimate` set) | `store_price_index.index_pct`, `.ci95_low_pct`, `.ci95_high_pct`, `.n_visits`, `.home_spend_month_eur`, `.ticket_gap_pct`, `.est_saving_month_eur` |
| `down_payment_plan` (optional, post-MVP) | How much could I put aside for a down payment, and how long would it take | `metric` with components (`estimate` set) | `metrics.md` section 11 (no SQL yet) |

Method ids are `<metric>.<output column>@<version>`. `<metric>` is the SQL file in `core/metrics/` without its number, and the output column is the one `metrics.md` lists, so every number points at the exact definition that produced it. `spending.*` and `evidence.row_count` are plain sums and counts over a filter, which `metrics.md` does not need to define. Values the user typed carry `user_input@1`.

Typed signatures (`data` is what the tool returns besides the card):

```text
get_spending(period: PeriodArg, filter?: Filter,
             direction?: "out" | "in",                      # default "out"; "in" for income categories
             group_by?: "none" | "category" | "basket" | "merchant" | "mcc_group" | "month" | "week",
             compare_to?: "none" | "previous_period" | "same_period_last_year" | "typical",
             top_n?: 1..10)                                  # default 5, the rest folded into "other"
  -> { period: Period, total: Number, tx_count: Number, comparison: Comparison | null,
       groups: { key, label, amount: Number, share: Number | null, change: Number | null,
                 flags: ("one_off" | "habit")[] }[] }

get_basket_breakdown(period: PeriodArg)
  -> { period: Period, total: Number,
       baskets: { key: Basket, label, amount: Number, share: Number,
                  top_categories: { key: Category, label, amount: Number }[] }[],
       overrides_applied: { target: Category | MerchantAlias, from: Basket, to: Basket }[] }

get_recurring_bills(include_income?: boolean)              # metrics.md section 2; window = last 6 complete months
  -> { bills: { bill_id, label, category: Category, cadence: "monthly", typical_month: Number,
                status: "spread" | "done_this_month" | "upcoming" | "late" | "skipped_this_month",
                last_paid: date, next_expected: date | null, due_until_payday: Number }[],
       income: { key, label, typical_month: Number, next_expected: date | null }[],
       upcoming_total: Number, next_payday: date,
       salary_status: "received_this_month" | "upcoming" | "late" | "no_salary_series" }
       # Salary Sweep is a transfer: never listed as a bill (metrics.md 2.3).
       # "upcoming" includes the typical day itself; an unpaid bill becomes "late" the day after.

get_safe_to_spend()                                         # metrics.md section 3: the 7 days after today
  -> { period: Period, safe_to_spend: Number,
       free_until_payday: Number, balance_limit: Number, budget_limit: Number,
       binding_limit: "balance" | "budget",
       components: { key: "balance" | "bills_due" | "essentials_reserve" | "irregular_reserve" | "cushion",
                     label, operation: "add" | "subtract", amount: Number }[],
       status: "ok" | "below_usual" | "nothing_free", next_payday: date,
       salary_status: "received_this_month" | "upcoming" | "late" | "no_salary_series" }
       # no_salary_series with no other recurring income: the result is 0 and the answer says
       # the coach cannot estimate it

run_what_if(selection: { kind: "category", value: Category }      # metrics.md section 4
                     | { kind: "basket", value: Basket }
                     | { kind: "mcc", value: string }               # comma-separated MCC codes, e.g. "4121"
                     | { kind: "merchant", value: MerchantAlias },
            cut_pct: 1..100)
  -> WhatIfResult                                           # same shape as POST /api/whatif:
                                                            # status: "estimate" | "estimate_with_caveat" | "not_offered",
                                                            # baseline, saving per month/week/year, one_off_excluded,
                                                            # regular_excluded. Baseline = last 6 complete months,
                                                            # one-offs left out; regular essentials are never cut.
  # POST /api/whatif takes a merchant id; the model only knows aliases. The server maps alias <-> id.

get_spender_profile()                                       # metrics.md section 5; last 6 complete months
  -> { period: Period,
       profile: { key: "not_enough_income_data" | "stretched" | "big_ticket" | "everyday_heavy"
                     | "saver" | "steady", label, description },
                # not_enough_income_data: no verdict; the answer says the account shows too little income
       traits: { key: "salary_moved_elsewhere" | "went_below_zero" | "regular_investor"
                    | "weekend_spender" | "frequent_small_purchases", label, note }[],
       features: { key, decides_label: boolean, value: Number }[] }   # e.g. keep_rate, everyday_share_pct
       # no feature uses Health on its own, labels and traits hold no sensitive terms (R9)

get_peer_benchmark(metric: "spend_total" | Basket
                         | "Groceries" | "Restaurants" | "Transportation" | "Entertainment" | "Lifestyle"
                         | "Travel" | "Home & Tech" | "Utilities" | "Housing")   # Health is never benchmarked (R9)
  -> { period: Period, you: Number, peer_median: Number, peer_p25: Number, peer_p75: Number,
       percentile: Number, vs_median: Number,
       peer_group: { level: "age_band+area3" | "age_band+city" | "age_band" | "all",
                     label, size: Number, comparable: boolean } }
     | { shown: false, reason: "group_too_small" | "not_comparable" }    # then no card
       # metrics.md section 6: the most specific level with at least 20 other peers; monthly averages

compare_store_prices()                                      # metrics.md section 7; groceries, last 365 days
  -> { stores: { merchant: MerchantAlias, label, is_s_group: boolean | null, price_index: Number,
                 price_index_ci95: { low: Number, high: Number } | null, differs_from_average: boolean,
                 visits: Number }[],
       switch: { status: "estimate" | "within_noise" | "already_lowest" | "not_measurable" | "no_alternative",
                 home: MerchantAlias, alternative: MerchantAlias | null, home_spend_month: Number,
                 ticket_gap: Number | null, estimated_saving: Number | null },   # set only for "estimate"
       caveats: string[],
       bonus_estimate: Number | null }                     # S-Bonus, once the #4 rules exist
       # Until the full-population run confirms the index, the coach never presents a switch as a saving.
```

**Not in v1.** Two features are left out on purpose:
- **Basket overrides:** #6 defines how a user can move a category or merchant to another basket. The tools already report `overrides_applied`, but the endpoint that stores an override is not part of this contract. Adding it is a follow-up issue.
- **Mortgages (decided, narrow scope):** R8 stays. The coach never predicts or scores a mortgage or credit decision. The only mortgage-related help is `down_payment_plan` below, an **optional post-MVP** tool. It answers "how much could I put aside for a down payment, and how long would it take" from the customer's own cash flow. Its formula belongs to `metrics.md`. It reads none of the mortgage tables. Until it is built, a down-payment question routes to `decline(out_of_scope)` with its own template: the coach says it cannot plan a down payment yet, and offers "How could I save more?" and "What can I safely spend this week?" instead.

Optional post-MVP tool:

```text
down_payment_plan(target_eur: number,                      # metrics.md section 11; the user's own target,
                  start_eur?: number,                       # the coach never suggests a home price; default 0
                  cuts?: { selection, cut_pct }[])          # optional what-if cuts that add to the capacity
  -> { target: Number,                                      # eur, user_input@1
       capacity_month: Number,                              # eur_per_month: income minus spending, last 6 complete months
       capacity_plan: Number,                               # eur_per_month: capacity plus the chosen cuts
       months_to_target: Number | null,                     # unit months; null when not reachable at this pace
       keep_low: Number, keep_high: Number, negative_months: Number,   # how steady the pace is
       status: "estimate" | "not_reachable" | "not_estimated",         # not_estimated: salary moved elsewhere
       assumptions: string[] }
  card: metric with components, estimate set (R13). Method ids and formula: metrics.md.
```

### 6.3 Control functions

The planner also gets three functions that touch no data:

| Function | Arguments | Effect |
|---|---|---|
| `decline` | `kind`: `investment_advice`, `credit_decision`, `out_of_scope`, `other_person_data` or `unsafe` | Ends the turn with the fixed, localised refusal template for that kind, plus 2 or 3 example questions. No data tool runs (R7, R8, R10). |
| `ask_clarifying_question` | `question` (up to 140 characters), `options` (up to 3 short strings) | Ends the turn with `outcome: "clarify"`. The question and the options pass the output validator and reach the app as `done.clarify` (contract, section 7.2). |
| `finish` | none | Data collection is complete; go to the composer. The model may call it in the same turn as the data tools. |

The tests for R6 and R10 read "no **data** tool call", because `decline` is a function call that reads no data. Confirmed by the team lead; the research document is being aligned.

### 6.4 What the model receives from a tool (R3)

Each function response carries the tool's `model_view`: numbers reduced to `{id, value, unit, label}`, periods reduced to their label, merchants replaced by aliases, and no evidence refs. An example for `get_spending` (values are illustrative and match the contract example):

```json
{
  "tool": "get_spending",
  "period": "September 2026",
  "total": { "id": "n1", "value": 2315.6, "unit": "eur", "label": "Total spending" },
  "comparison": {
    "baseline": { "id": "n2", "value": 1948.2, "unit": "eur", "label": "August spending" },
    "change": { "id": "n3", "value": 367.4, "unit": "eur", "label": "Change vs August" },
    "change_pct": { "id": "n4", "value": 18.9, "unit": "percent", "label": "Change vs August" }
  },
  "groups": [
    { "label": "Travel", "amount": { "id": "n5", "value": 240.0, "unit": "eur" }, "change": { "id": "n6", "value": 240.0, "unit": "eur" }, "flags": ["one_off"] },
    { "label": "Restaurants", "amount": { "id": "n7", "value": 312.8, "unit": "eur" }, "change": { "id": "n8", "value": 91.7, "unit": "eur" }, "flags": ["habit"] },
    { "label": "Everything else", "amount": { "id": "n9", "value": 1762.8, "unit": "eur" }, "change": { "id": "n10", "value": 35.7, "unit": "eur" }, "flags": [] }
  ],
  "notes": []
}
```

The declaration sent to Gemini for the same tool (shortened to the main arguments):

```json
{
  "name": "get_spending",
  "description": "Total spending or income of the current user for a period, optionally filtered, grouped and compared with an earlier period. Returns numbers with ids; cite them as {{id}}.",
  "parameters_json_schema": {
    "type": "object",
    "properties": {
      "period": {
        "type": "object",
        "properties": {
          "preset": { "type": "string", "enum": ["this_week", "last_week", "this_month", "last_month", "last_3_months", "last_6_months", "last_12_months", "year_to_date", "custom"] },
          "start": { "type": "string", "format": "date" },
          "end": { "type": "string", "format": "date" }
        },
        "required": ["preset"]
      },
      "filter": {
        "type": "object",
        "properties": {
          "categories": { "type": "array", "items": { "type": "string", "enum": ["Groceries", "Restaurants", "Transportation", "Utilities", "Entertainment", "Health", "Home & Tech", "Housing", "Lifestyle", "Travel", "Salary", "Other Income", "Invest Withdraw", "Invest Deposit", "Salary Sweep"] } },
          "baskets": { "type": "array", "items": { "type": "string", "enum": ["regular_essentials", "unexpected_necessities", "everyday_spending"] } }
        }
      },
      "group_by": { "type": "string", "enum": ["none", "category", "basket", "merchant", "mcc_group", "month", "week"] },
      "compare_to": { "type": "string", "enum": ["none", "previous_period", "same_period_last_year", "typical"] }
    },
    "required": ["period"]
  }
}
```

### 6.5 Intents and expected tools

The planner chooses tools freely. The eval set (section 9) checks that each canonical intent uses the expected tools.

| Intent | Example question | Expected tools |
|---|---|---|
| Where did my money go? | "Where did my money go?" | `get_spending` (group by category, compared with the previous period), `get_basket_breakdown` |
| What kind of spender am I? | "What kind of spender am I?" | `get_spender_profile`, `get_peer_benchmark` |
| What can I safely spend this week? | "What can I safely spend this week?" | `get_safe_to_spend`, `get_recurring_bills` |
| How could I save more? | "How could I save more?" | `get_basket_breakdown`, `compare_store_prices`, `get_recurring_bills`, then `run_what_if` |
| Specific follow-ups | "And restaurants?", "What if I cut that by 20%?" | `get_spending` with a filter, `run_what_if` |
| Down payment (post-MVP) | "How long would it take to save a down payment?" | `down_payment_plan`, `get_recurring_bills`. Until the tool exists: `decline(out_of_scope)` with the "not yet" template. |
| Credit decision | "Will the bank approve my mortgage?" | `decline(credit_decision)` |
| Investment, other people, off topic | "Should I buy tech stocks?" | `decline` |

## 7. Conversation flow

### 7.1 One answer, step by step

| Step | What happens | Stream events |
|---|---|---|
| 0. Validate (before the stream) | Check the body, including an empty message or one over 500 characters (400 `invalid_request`), the customer (404 `customer_not_found`) and the rate limit (429 `rate_limited`). These are plain HTTP errors: the stream is not opened yet. | none |
| 1. Start | Open the stream. Resolve the conversation: it belongs to one customer, so an id that is unknown, expired or owned by another customer starts a new conversation (`warnings: conversation_reset`), and earlier tool results are never reused. Resolve the language: the request value, or a detector for `auto`. If the detector is unsure, use the previous turn's language, then the persona default. | `meta` |
| 1a. Input guard | Strip control characters. Flag injection markers, investment keywords and references to other people as hints for the planner and the audit log. Nothing is blocked on keywords alone, because "How much did I invest?" is a valid question about the user's own Invest Deposit history (R7). | `status` (`understanding`) |
| 2. Plan, model call 1 | Gemini gets the planner system prompt, the masked history, the question and the 8 data tools plus 3 control functions. Mode `ANY`: the model must call a function. It may return several calls in parallel. | |
| 3. Tools | Validate the arguments; on an error, return it to the model as a function response. Run valid calls in parallel on the 3-connection pool. Register number ids and evidence. Build cards. | `status` (`tool`) per tool, `card` per card-worthy result |
| 4. Loop | If the model did not call `finish`, send the function responses back (model turns appended verbatim) and call again in mode `ANY`. At most 2 tool rounds and 6 data calls, then go to the composer anyway. `decline` or `ask_clarifying_question` ends the turn at once. | |
| 5. Compose, model call 2 | A fresh, tool-free request: the composer system prompt, the question, the language, the masked previous turn and a quoted DATA block holding the tools' `model_view`s. Output is JSON constrained by the `AnswerDraft` schema. | `status` (`writing`) |
| 6. Validate | Schema plus semantic checks (section 7.4). On failure, retry once with the list of errors added. On a second failure, use a template answer from the tool results (`outcome: "fallback"`) (R12). | |
| 7. Deliver | Send the validated text sentence by sentence. Before a sentence that cites a number not sent yet, send a `numbers` event. Then send `done` and write the audit record (R15). | `numbers`, `delta`, `done` |

A typical answer needs two model calls: one planner call, with `finish` in the same turn, and one composer call. Cards reach the screen as soon as the tools finish, before the text is written.

### 7.2 Why the composer is a separate, tool-free call

- **R12** needs answer output validated against a schema. The Gemini docs describe combining structured output with function calling as a **preview** available only on some newer models (section 12). A separate call works on any current model and keeps the planner simple.
- The composer gets tool data as a quoted block in a fresh request, not as instructions, which makes R11 explicit. Because it is a fresh call, there is no thought-signature history to keep for it.
- **Cost:** about one extra second compared with letting the planner write the answer. The latency budget absorbs it (section 10), and cards are already on screen during that time.

`AnswerDraft`, the JSON schema given to the composer:

```json
{
  "type": "object",
  "properties": {
    "language": { "type": "string", "enum": ["en", "fi"] },
    "text": { "type": "string", "description": "The answer, at most 120 words. Cite every number as {{id}} using ids from DATA. Write no digits." },
    "cited": { "type": "array", "items": { "type": "string" }, "description": "Every id used in text." },
    "lesson_key": { "type": ["string", "null"], "enum": ["one_off_vs_habit", "fixed_vs_flexible", "safety_buffer", "small_amounts_add_up", "price_level", "estimate_not_promise", "peer_context", null] }
  },
  "required": ["language", "text", "cited", "lesson_key"]
}
```

R12 says the model returns cards. In this design the cards are built by the server from tool results, and the model's JSON only refers to numbers by id. Cards stay correct even when the composer fails, and they arrive before the text. This reading of R12 is confirmed by the team lead.

### 7.3 Numbers in text

- **Tokens:** the composer writes `{{n3}}` wherever it means a number. The server replaces the token with the Number's `display` in the user's locale: Finnish `1 234,56 €` and `9,8 %`, English `€1,234.56` and `9.8%` (R14). The app receives both the tokenised `text` and `text_rendered` (contract, section 2.4).
- **Dates:** the composer may write dates and periods in natural language, inflected as the language requires, for example "syyskuussa 2026" or "on 1 October". Their digits must come from dates the tools returned in this turn (section 7.4, rule 3). When the user's period was relative ("last month"), the composer names the resolved period (R5).
- **Glossary terms (#34):** the composer may mark a financial term as `{{t:key}}`, or `{{t:key|surface form}}` when the sentence inflects it, as Finnish does.
  - **Fixed glossary:** `key` must come from `core/config/glossary.yaml`. The composer prompt lists the allowed keys with each term in the answer's language, plus one rule: mark only terms from this list, and never write a definition.
  - **Definitions:** the server attaches the definitions and the customer's own number in the `personal` line from the glossary and the tools. They are not model text.
  - **Emphasis:** at most one bold span (`**…**`) for the main takeaway, and at most 3 emphasised spans in total, bold and terms together (contract, section 2.5).

### 7.4 Output validator

The validator runs on every composer output. Any failure triggers the single retry, then the template.

1. The JSON matches `AnswerDraft`. Keywords such as `maxLength` are not enforced by Gemini (section 12), so the validator checks length itself: at most 120 words.
2. Every `{{id}}` exists among this answer's numbers, and `cited` equals the set of tokens used.
3. **No stray digits (R1):** remove the `{{id}}` tokens, then look at every remaining run of digits. A run passes only if it is part of a date the tools returned in this turn: the day, month or year of a resolved period, or of a date field such as `next_expected`, or a digit run inside a period label. Anything else fails, including amounts, percentages and counts. Matching digit runs instead of whole label strings lets Finnish inflect month names ("syyskuussa 2026" against the label "syyskuu 2026"). Merchant labels contain no digits.
4. The language of `text` matches the resolved language (R14).
5. **Deny lists:** sensitive inferences such as health, pregnancy, religion or politics (R9); investment imperatives ("buy", "sell" next to an instrument word) (R7); promises ("guaranteed", "will save") on estimates (R13).
6. No URLs, markdown links or HTML.
7. `lesson_key` is in the lesson catalogue or null.
8. **Term tokens and emphasis.** These are repaired, not retried, because they cannot change a number:
   - **Unknown key:** a term token whose key is not in the glossary is dropped. Its surface form stays as a plain word (if there is none, the token disappears), and the event is logged.
   - **Over the limit:** beyond 3 emphasised spans, the extra term tokens (the last ones first) become plain words. A second bold span loses its markers. Both are logged.
   - **Surface form:** it must not contain digits or braces, so it cannot smuggle in a number (R1).

**Residual risks:**
- A number written as a word ("twice as much") passes rule 3.
- An invented number that happens to equal a date part, for example "1" or "2026", also passes.
- **Numbers in tool arguments:** the model passes numbers as tool arguments, for example `cut_pct` in `run_what_if` or `target_eur` in `down_payment_plan`. Nothing yet checks them against what the user typed, so the model could turn "cut a bit" into 20. The tool output labels such a value as `user_input@1`, so it is visible, but not verified. A later issue adds an argument check: every numeric argument must appear in the user's message (parsed with the locale's number format) or in the `scenario` of an action the user tapped. Otherwise the planner must call `ask_clarifying_question`.

The composer prompt forbids both, and the eval set samples for them.

### 7.5 Cards

- **Source:** cards are built only from tool results, in the order the tools were called, with at most 3 per answer. The card type per tool is listed in section 6.2.
- **Estimates:** cards for safe to spend, what-if and store savings always carry `estimate` with a plain-language assumption (R13).
- **Partial answers:** a tool that failed produces no card. The answer says the data could not be computed and never guesses.

### 7.6 Follow-ups, memory and lessons

- **Memory:** an in-memory store keyed by `conversation_id`, keeping the last 6 turns for 30 minutes on a single instance. Production would use a shared store.
  - A conversation belongs to the customer who started it. A request with a `conversation_id` that is unknown, expired or owned by another customer starts a new conversation and never sees earlier tool results (R4).
  - The planner gets the previous questions, its previous function calls and their compact results, so "and last month?" or "what if I cut that by 20%?" resolve without the app resending anything.
  - The composer gets only the previous question and answer with numbers masked as `[number]`. It cannot copy an old number; it has to cite a fresh tool result.
- **Follow-up suggestions** (`follow_ups`): a deterministic, localised table per intent and tool. It always offers the partner's four questions, minus the one just asked, and never depends on the model.
- **Lessons** (financial literacy): a catalogue of about 7 short, human-reviewed concepts in English and Finnish (the `lesson_key` enum above). The composer picks at most one key that fits the answer, and the server inserts the reviewed text. The model never writes the lesson itself.

### 7.7 Languages (R14)

- **Prompts:** system prompts are in English and tell the model to answer in the resolved language.
- **Server-side text:** labels, period labels, refusal templates, follow-ups and lessons come from catalogues in English and Finnish, which a Finnish speaker reviews before the demo.
- **Labels:** basket labels follow the partner's vocabulary (contract, section 1). Finnish basket labels are an open question (section 13).

### 7.8 The coach asks: spike reviews (#33)

The coach does not only answer; it also asks. When it sees a spending spike, it asks one question: was this an unexpected necessity or everyday spending? The customer's answer is stored as a label on that transaction and changes the numbers (`metrics.md` section 1.1). The person decides what their own spending means.

**Which spike to ask about.** The core picks candidates deterministically; the model never chooses. A candidate is a transaction that:
- is a one-off by the spike rule (`metrics.md` section 0), in the spend flow, inside the window;
- is in `unexpected_necessities` or `everyday_spending` by the basket rules;
- is **not** Health and not a health MCC (5912, 8011, 8099, 8021). Those spikes are never asked about and stay in `unexpected_necessities` silently (R9);
- has never been asked about before (see "asked" below) and has no label.

The candidates are ordered **most recent first, then largest amount, then transaction id** (a final tiebreak, so the order is always deterministic). The first one is the next review to create.

**The life of a review.**

```text
  (candidate) --first serve--> PENDING --"needed" / "I chose it"--> ANSWERED
                                  ^   \                               |
                                  |    \--7 days, no answer--> CLOSED |
                                  +------- undo while open -----------+
     ANSWERED --undo after the 7 days--> CLOSED
```

- **PENDING** (created, not answered, open for 7 days from creation): the purchase is `unclassified`, "Waiting for your answer". It is in no basket total and not in the reserve for unexpected necessities. As a one-off it was never in the everyday run rate.
- **ANSWERED:** the purchase is in the chosen basket. "Needed" adds it to `unexpected_necessities` and its reserve, so safe to spend goes down. "I chose it" adds it to `everyday_spending`, and safe to spend does not change. No answer ever raises safe to spend (`metrics.md` section 1.1).
- **CLOSED** (no answer within 7 days, or undone after them): the purchase is back in the basket the rules give it, exactly as for a customer who was never asked.
- **Undo** while the review is open returns to PENDING. A closed review is never re-opened, and its transaction is never asked about again.

So a customer with no pending review has exactly the numbers of the published worked examples. Only the pending state differs.

**Creating reviews, "asked", and the limits.**
- **Asked means created.** A review is created, and so counts as asked, the first time the server serves it, either in `reviews` of `GET /api/overview` or as a card attached to an answer.
- **One at a time.** A customer has at most one PENDING review. While it is pending, the server serves the same review again and never creates another; `reviews` therefore holds at most one item. A new review is created only after the previous one is answered or closed.
- **Creation is idempotent:** an upsert keyed by customer and transaction, so concurrent overview calls cannot create two. This is the only write a GET makes, and it touches only the review table, not the metrics. The overview therefore stays safe to call on every app open; a prefetch that gets a new review counts as asking it.
- **Weekly limit:** at most **3 reviews created per customer per calendar week** (Monday to Sunday, Helsinki time).
- **Never twice:** a transaction gets at most one review, ever.
- **Clock:** creation, expiry and the weekly limit run on the **wall clock** (`now()`), not on `DEMO_TODAY`, which is frozen for the demo. A demo reset deletes the persona's rows from the review table, with an admin script in the implementation issue. Nothing else needs resetting, because labels live only there.

**Storage: one small table.**

```sql
CREATE TABLE spike_reviews (
    customer_id  text   NOT NULL,
    tx_id        bigint NOT NULL,              -- transactions.id; never sent to the app or the model
    tx_ref       text   NOT NULL UNIQUE,       -- 'txr_' + 16 random lowercase letters and digits, sent to the app
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,         -- created_at + 7 days
    basket       text CHECK (basket IN ('unexpected_necessities', 'everyday_spending')),  -- NULL while pending, closed or undone
    answered_at  timestamptz,
    PRIMARY KEY (customer_id, tx_id)
);
-- state: ANSWERED if basket IS NOT NULL; PENDING if basket IS NULL AND now() < expires_at; otherwise CLOSED
```

- `tx_ref` is a random token created with the review. It is not derived from the transaction id, so it reveals nothing and needs no secret.
- Only reviewable spikes get a `tx_ref`. The label endpoint therefore cannot label a Health purchase or any other transaction: R9 holds by construction, not only by validation.
- Evidence rows still show a `tx_id`, including the review card's own "See the purchase" evidence for the same transaction. Making evidence ids opaque is a follow-up. What holds: the label endpoint accepts only a `tx_ref`, never a `tx_id`, and a `tx_ref` is not derived from one.

**Recomputing with labels.**
- **Classification:** the review table feeds the transaction level of the overrides in the shared classification block. An ANSWERED row puts the purchase in its `basket`, a PENDING row puts it in `unclassified`, and a CLOSED row adds nothing. Every metric that uses the block (baskets, safe to spend, safe to save, what-if, profile, peer) picks this up the same way.
- **Marts:** the precomputed marts of `metrics.md` section 8 are refreshed for that customer after a label.
- **Evidence:** the evidence spec (section 5.2) includes the customer's **label set**, the sorted list of `(tx_id, basket)` pairs in effect. A pending review counts as `(tx_id, unclassified)`. A number after a label therefore gets a new ref. A ref issued before the label keeps resolving to the number as it was, with the old label set, so it still reconciles (R2).
- **Cache:** the tool cache key (section 6.1) includes a hash of the label set, so a label invalidates exactly that customer's cached results.

**The label endpoint, not a tool (R6).** `POST /api/baskets/label` (contract, section 10) is called by the **app** when the customer taps an answer.
- The model has no tool that writes data. The tool registry is unchanged, and the planner cannot label, undo or dismiss anything.
- The endpoint checks that the `tx_ref` belongs to the customer and that the basket is one of the two options. An unknown ref and another customer's ref get the same 404, so nobody can probe for refs (R4). Late answers are accepted: any `tx_ref` the customer was shown can be labelled, also after the review closed (contract, section 10.1).
- Every label write goes to the audit log: customer, `tx_ref`, basket, time.

**Review cards in answers.**
- **When:** the server, not the model, may attach a review card to an `/api/ask` answer when the answer's tools touched the spike's basket or category.
  - If a review is pending, it attaches **that** review and never a second one.
  - Otherwise it may create the next one, within the weekly limit.
- **Limits:** the card counts towards the limit of 3 cards per answer.
- **Text:** the question and the option texts are fixed, reviewed templates in English and Finnish. The model never writes them.
- **Pending purchases in answers.** While a review is pending, the tool results show the purchase as `unclassified` ("waiting for your answer"). The composer prompt states: a pending purchase is waiting for the customer's answer, so describe it that way and never assign it to a basket. For example, "the 1,080.42 Home & Tech purchase is waiting for your answer, so it is not in any basket yet". The validator's deny list rejects text that calls a pending purchase "needed", "essential" or "everyday".

**Safe to save.** The overview's `safe_to_save` card (its own card type) carries two figures, defined in `metrics.md` section 3.1:
- **Headline:** the monthly figure, what a typical month leaves (product decision).
- **Second line:** the stock, money on the account beyond what is needed until payday, with one fixed explanatory sentence and no call to action.
- **When the month leaves nothing:** the headline is 0, and a `reason` built from the data says why. The rule is on the sign of free month: if it is negative, essentials exceed income; if not, the largest everyday category is named (never a sensitive one, R9).

Both figures are estimates (R13), and nothing says where to put the money (R7). The coach presents them as separate from safe to spend, not added to it. The coach's text may cite these numbers like any other tool number, but it never adds a suggestion to move or invest money; the validator's deny list covers "move", "transfer" and "invest" next to a safe-to-save number.

## 8. Guardrails

| Risk | Control | Rule |
|---|---|---|
| An invented or miscalculated number | Number tokens, the digit check in the validator, retry, then template | R1, R12 |
| A number that cannot be traced | Every Number has `evidence_ref`, which resolves and reconciles | R2 |
| Raw data reaching the model | `model_view` projections, merchant aliases, masked history. A canary merchant id in the test data must never appear in a logged prompt. | R3 |
| Another customer's data | `customer_id` lives only in the server context. Tools have no customer argument. Evidence checks ownership. | R4 |
| Future or ambiguous periods | Clamping to `as_of`, resolved periods in every Number, period labels in the text | R5 |
| Actions with side effects | Read-only registry, no free-text arguments. A spike label is written only by the app through `POST /api/baskets/label` when the customer taps an answer; no tool can write it (section 7.8). | R6 |
| Investment advice | `decline(investment_advice)`, a fixed template with general education and a pointer to an S-Pankki adviser, and a validator deny list. The user's own Invest Deposit and Withdraw history stays answerable. | R7 |
| Credit decisions, mortgages | "Will the bank approve my mortgage?" and similar questions route to `decline(credit_decision)`: a fixed template that points to the bank's loan process. No tool scores creditworthiness, and the mortgage tables are not used to rate the user. Saving for a down payment is allowed through the post-MVP `down_payment_plan` tool, which uses only the user's own cash flow. | R8 |
| Sensitive inferences | Profile traits and insights never use the Health category or health MCCs. Health appears only as an amount in a full breakdown or when asked about directly. Validator deny list. A Health or health-MCC spike is never asked about, gets no `tx_ref` and so cannot be labelled (section 7.8). | R9 |
| Off-topic questions | `decline(out_of_scope)` with 2 or 3 example questions. No data tool runs. | R10 |
| Prompt injection | User text is wrapped and marked as data. Tool data holds no external free text (merchants are anonymised, then aliased). Tool arguments are schema-validated enums. The composer sees data in a quoted block. The validator does not depend on the model. Even a successful injection cannot switch customer, run SQL, see rows or emit an unvalidated number. | R11 |
| Malformed model output | `AnswerDraft` schema, one retry, then the template | R12 |
| Estimates taken as promises | `estimate` on cards, the "estimate_not_promise" lesson, a deny list for promises | R13 |
| Unclear AI use, wrong language | `ai_disclosure` in the overview, language resolution, locale formats | R14 |
| No accountability | An audit record for every answer, and the eval set gates merges into `main` | R15 |

**Tone:** the coach describes and never shames. User-facing labels avoid judgemental words; for example, the internal idea of "leakage" is shown as "Everyday spending".

**Refusal templates** (`decline`): one per kind, in English and Finnish, each with 2 or 3 example questions the coach can answer. They are fixed text, reviewed by a human. The model only chooses the kind.

## 9. Audit log and eval set

### 9.1 Audit record (R15)

Every `/api/ask` call writes one record, whatever the outcome.
- **Storage:** append-only JSON Lines under `AUDIT_LOG_DIR` (default `var/audit/`, which must be added to `.gitignore` when this is implemented).
- **Lookup:** records can be read back through the internal endpoint `GET /api/audit/{answer_id}` (team and eval use only, not part of the app contract).
- **Content:** the record holds aggregates and the question, never transaction rows. With synthetic data, retention is the length of the event.

```json
{
  "answer_id": "ans_7f3k9q2m",
  "conversation_id": "conv_4h8j2n6p",
  "created_at": "2026-11-13T21:07:12+02:00",
  "customer_id": "CUST00042",
  "as_of": "2026-09-30",
  "language": { "requested": "auto", "resolved": "en", "detector": "en" },
  "question": "Where did my money go?",
  "guard_flags": [],
  "model": { "id": "<GEMINI_MODEL value>", "planner_prompt": "planner@1", "composer_prompt": "composer@1" },
  "planner_turns": [
    {
      "mode": "ANY",
      "calls": [
        { "name": "get_spending", "args": { "period": { "preset": "this_month" }, "group_by": "category", "compare_to": "previous_period", "top_n": 2 }, "status": "ok", "latency_ms": 142, "evidence": ["ev_k3m5p7r9t1v3", "ev_m3o5q7s9u1w3"] },
        { "name": "finish", "args": {}, "status": "ok", "latency_ms": 0, "evidence": [] }
      ],
      "latency_ms": 1180,
      "tokens": { "input": 2210, "output": 64 }
    }
  ],
  "tool_outputs": { "get_spending#1": "<full ToolResult.data, aggregates only>" },
  "numbers": { "n1": { "value": 2315.6, "method": "spending.total@1", "evidence_ref": "ev_k3m5p7r9t1v3" } },
  "composer_attempts": [
    { "raw": "{\"language\":\"en\",\"text\":\"September cost {{n1}}, ...\",\"cited\":[\"n1\",\"n3\",\"n5\",\"n8\"],\"lesson_key\":\"one_off_vs_habit\"}", "validation": "ok", "latency_ms": 1460, "tokens": { "input": 1530, "output": 118 } }
  ],
  "outcome": "answered",
  "refusal": null,
  "text": "September cost {{n1}}, ...",
  "text_rendered": "September cost €2,315.60, ...",
  "cards": ["card_ans7f_01"],
  "warnings": [],
  "latency_ms": { "first_card": 1390, "done": 3020 }
}
```

### 9.2 Eval set

A fixed set, run before every merge into `main` (R15):
- **Per persona:** the four partner questions and two follow-ups each, in English and Finnish.
- **Red-team sets:** investment advice, mortgage or credit, other people's data, off-topic and prompt injection (in user text, and in a planted merchant label).

For each question it checks:
- **Tools:** the expected tools from section 6.5 were called.
- **R1:** the validator passed with no fallback.
- **R2:** every `evidence_ref` resolves and reconciles.
- **Refusals:** refusal questions got the right `refusal.kind`.
- **R3:** the canary merchant id never appears in a logged prompt.

The target is 100% on R1, R2 and the refusal sets.

## 10. Latency budget

Targets for the demo on the dev environment. The p50 column is the target; the hard limit triggers the fallback.

| Step | p50 | Hard limit | Note |
|---|---|---|---|
| `GET /api/overview` | 300 ms | 1 s | Precomputed snapshot, no model |
| `POST /api/whatif` | 300 ms | 1 s | No model |
| `GET /api/evidence` | 300 ms | 2 s | One indexed per-customer query |
| `POST /api/baskets/label` | 500 ms | 3 s | One write, then the per-customer refresh of section 7.8 before it returns |
| `/api/ask`: `meta` event | 100 ms | | |
| Planner call | 1.2 s | 6 s | One retry on 429 or 5xx if the budget allows |
| Tools, in parallel | 0.3 s | 5 s per statement | `statement_timeout = '5s'` |
| First `card` on screen | about 1.6 s | | |
| Composer call | 1.5 s | 8 s | Retry once on a validation failure |
| Validation, rendering, audit | under 20 ms | | |
| `done` | about 3.5 s | 15 s total | Past the limit: template answer, `outcome: "fallback"` |

## 11. Failure modes

| Failure | Detected by | Behaviour | Outcome seen by the app |
|---|---|---|---|
| Database down or slow | Connection error, `statement_timeout` | No retry within the request | Overview and evidence: 503 `data_unavailable`. Ask: `error` event. |
| One tool fails or times out | Exception in the tool | `{error: <code>}` goes back to the model, and that tool produces no card. The model may try another tool. The answer says what could not be computed. | Normal answer, with `warnings` |
| Invalid tool arguments | Pydantic validation | The error goes back to the model once. A second failure goes to the composer with the data so far, or to `clarify`. | Normal answer or `clarify` |
| Model calls an unknown function | Name not in the registry | Same as invalid arguments | |
| Planner: 429, 5xx or timeout | SDK error | Retry once. Then a keyword router maps the question to the closest canonical intent, runs its tools and answers with a template. | `fallback` |
| Composer: error, invalid JSON or validator failure | SDK error or validator | Retry once with the error list, then the template answer from the tool results (R12) | `fallback` |
| Safety block from Gemini | Response finish reason | Refusal template `unsafe` | `refused` |
| No data in the period | Tool `notes` | Zero values plus a note, and the answer says there were no transactions | `answered` |
| Period after `as_of` | Clamping | Clamped period plus a note (R5) | `answered` |
| Unknown or foreign `evidence_ref` | Evidence store | | 404 `evidence_not_found` or 403 `evidence_forbidden` |
| Conversation expired | Store lookup | Treated as a new conversation | `meta` carries a new `conversation_id` |
| Too many requests | Per-customer rate limit, proposed at 10 asks a minute | | 429 `rate_limited` |

The demo never shows an empty answer. The worst case is a template answer built from the cards.

## 12. Gemini integration notes

Sources checked on 2026-11-13:
- `google-genai` Python SDK documentation through Context7 (`/googleapis/python-genai`).
- https://aistudio.google.com/docs/function-calling, the redirect target of `ai.google.dev/gemini-api/docs/function-calling`. The first 100,000 characters were read.
- https://aistudio.google.com/docs/structured-output.

**Planner:** `client.models.generate_content` with `types.GenerateContentConfig`:
- `system_instruction` holds the planner prompt.
- `tools=[types.Tool(function_declarations=[...])]`. Each declaration uses `parameters_json_schema` generated from the Pydantic argument model.
- `automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)`, because the orchestrator runs tools itself.
- `tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY"))`. The model must return function calls, which makes routing (data tools or `decline`) always structured.

**Tool results:** `types.Part.from_function_response(name=..., response={"result": model_view})`, or `{"error": code}`, inside `types.Content(role="tool", parts=[...])`. Several parallel calls are answered in one content.

**History:** each model turn is appended exactly as received (`response.candidates[0].content`). For stateless use the docs require model steps "exactly as received", which keeps the thought signatures newer models attach to function calls.

**Composer:**
- `response_mime_type="application/json"` and `response_json_schema=AnswerDraft.model_json_schema()`, with no tools.
- The docs list supported JSON Schema keywords and say that `minLength`, `maxLength` and similar keywords are not enforced, so the validator checks them.
- Combining structured output with function calling is documented as a preview for some Gemini 3 and 4 models only. That is the reason for the separate composer call (section 7.2).

**Model and keys:**
- **Model:** the id comes from a new environment variable `GEMINI_MODEL`, to be added to `.env.example` in the implementation issue. It is pinned to one model version for the demo and recorded in every audit record.
- **API key:** `GEMINI_API_KEY`, which already exists.
- **Temperature:** the model's default, unless the model documentation advises otherwise. Consistency comes from the tools, not from sampling.

**Credits:** during development, model responses are cached on disk, keyed by a hash of model, prompt version and contents, so repeated runs do not spend credits.

**Risk: two API surfaces.**
- The SDK documentation shows `generate_content` with `tool_config` and `response_json_schema`.
- The current docs site shows a newer Interactions API (`client.interactions.create` with `tool_choice` and `response_format`). It also documents a `validated` function-calling mode.

This design uses `generate_content`: it is in the SDK docs, it is stateless, and the core keeps the history itself, which the audit log and the privacy boundary need. All Gemini calls sit in one adapter module, so moving to the other API changes one file.

## 13. Open questions

**For Renat (product):**
1. **Personas:** decided. Three customers are picked from the data in a separate issue, and invented first names are fine because the data is synthetic.
2. **Mortgages:** decided. The scope is narrow and R8 stays (section 6.2), and `down_payment_plan` comes after the MVP.
3. **Salary Sweep:** the category's meaning is unknown. Should it show as income, as a transfer, or be hidden?
4. **Finnish basket labels:** what is the official Finnish wording of "Regular essentials", "Unexpected necessities" and "Everyday spending"?
5. **Health category (R9):** decided. Health appears only as a category amount inside a full breakdown. It is never singled out and never turned into a statement about the person.
6. **AI disclosure (R14):** decided default: "Explanations are written by AI. The numbers are calculated from your transactions."

**For Maxim (app):**
7. Is streaming with `fetch()` and a stream reader fine in the app stack, or should the app start with the JSON response (`Accept: application/json`) and switch later?
8. Are 3 cards per answer and 2 actions per card enough?
9. Does v1 need time-series charts (`display_hint: "time_series"`)?

**For #6 (metrics):**
10. `metrics.md` now settles the profile keys and traits, the age bands, the peer levels and the minimum group of 20, the safe-to-spend window and components, and the what-if baseline. It also settles the what-if and store-switch statuses and the output columns that method ids now use. This design and the contract follow it. Still open: how the remaining period presets resolve, and that document's own open questions (its section 10).

## 14. Coverage of the issue and of the research rules

**"Must define" in issue #5:**

| Item | Section |
|---|---|
| Tool registry: names, typed arguments, typed outputs (spending, recurring bills, baskets, safe to spend, what-if, spender profile, peer benchmark, store prices; plus the optional `down_payment_plan`) | 6.1, 6.2, 6.4; contract section 3 |
| Every number as `{value, unit, period, method, evidence_ref}`, and how evidence is retrieved | 5; contract sections 2.1 and 9 |
| Conversation flow: tool calls, then an answer with cards; follow-up questions; English and Finnish | 7.1 to 7.7; contract section 7 |
| Guardrails: refusals, prompt-injection handling, never a number without a tool | 6.3, 7.4, 8 |
| Audit log of each answer, latency budget, failure modes | 9, 10, 11 |
| API: `POST /api/ask` (streaming), `GET /api/overview/{customer_id}`, `GET /api/evidence/{ref}`, `POST /api/whatif`, `GET /api/personas`; and from #33, `POST /api/baskets/label` | contract sections 5 to 10 |
| Use of the bank-assistant research (#3) | Rules R1 to R15 referenced throughout. Sections 1 to 5 of #3 were still in progress at the time of writing. |

**Research rules:**

| Rule | Where it is implemented |
|---|---|
| R1 No number without a tool | 5.1, 7.3, 7.4 |
| R2 Every number can be opened | 5.2, 9.2 |
| R3 Raw rows never reach the model | 4, 6.4, 7.6 |
| R4 Customer set by the server | 4, 5.2 |
| R5 Time stops at `DEMO_TODAY` | 4, 7.3 |
| R6 Read-only tools | 4, 6.1, 7.8 (labels are written by the app, not by a tool) |
| R7 No investment recommendation | 6.3, 7.1, 7.4, 8 |
| R8 No credit decision | 6.2, 6.3, 6.5, 8 |
| R9 No sensitive inferences | 6.2, 7.4, 7.8, 8 |
| R10 Out of scope declined briefly | 6.3, 8 |
| R11 Data is not instructions | 6.1, 7.2, 8 |
| R12 Structured, validated answers | 7.1, 7.2, 7.4, 11 |
| R13 Estimates are labelled | 7.5, 8; contract section 3 (`estimate`) |
| R14 AI disclosed, language follows the user | 7.3, 7.7; contract section 6 (`ai_disclosure`) |
| R15 Every answer logged, eval set gates the demo | 9 |
