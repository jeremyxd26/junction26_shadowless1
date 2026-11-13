# Core API contract

**Version:** 0.1.2 (draft) · **Issues:** #5, #32 · **Design:** [docs/design/agent-core.md](../docs/design/agent-core.md)

**Status:** draft 0.1. The app owner raises changes through a new issue, and each change bumps the version in the changelog.

This file is the interface between `core/` (the coach service) and `app/` (the mobile web app). The app can be built against the examples below before the core exists. Every example is tagged `<!-- example: <name> -->`, so a mock server can serve them by name.

All values in the examples are **illustrative**: they show shapes and consistent arithmetic, not results computed from the dataset. Metric definitions are owned by `docs/design/metrics.md` (issue #6). Method ids, enums and windows here follow it (section 2.1, `method`).

## Contents

1. [Conventions](#1-conventions)
2. [Shared objects](#2-shared-objects): Number, Period, Comparison, text with number tokens
3. [Cards](#3-cards)
4. [Errors](#4-errors)
5. [`GET /api/personas`](#5-get-apipersonas)
6. [`GET /api/overview/{customer_id}`](#6-get-apioverviewcustomer_id)
7. [`POST /api/ask`](#7-post-apiask) (streaming)
8. [`POST /api/whatif`](#8-post-apiwhatif)
9. [`GET /api/evidence/{ref}`](#9-get-apievidenceref)
10. [Changelog](#10-changelog)

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | `/api`. Request and response bodies are JSON in UTF-8, except the `/api/ask` stream (section 7). |
| Customer | Demo mode has no login: the app picks a persona from `/api/personas` and sends its `customer_id`. In production the customer comes from the bank session and the field is ignored. The core never lets the AI model choose the customer. |
| "Today" | Fixed by the server setting `DEMO_TODAY` (default `2026-09-30`). Every response carries it as `as_of`. Nothing after `as_of` is treated as history. Later dates are predictions such as an expected bill. |
| Language | `en` or `fi`. GET endpoints take `?lang=en` or `?lang=fi` (default `en`). POST bodies take `language`, and `/api/ask` also accepts `auto` (detect from the message). Every response says which `language` was used. All labels, `display` strings and texts arrive already localised. The app does not translate. |
| Dates | `YYYY-MM-DD`. Periods are inclusive at both ends. |
| Money sign | Spending, bills and income are **positive** amounts. A `change` is signed: positive means more than the baseline. A `components[]` entry carries a positive `amount` and an `operation` (`add` or `subtract`). Raw transaction rows in evidence keep the bank sign: negative means money out. |
| Numbers | **Every number in a response is a [Number object](#21-number).** There are two exceptions. Raw transaction amounts in evidence rows are decimal strings (section 9). The `scenario` of an `open_whatif` action is a request payload that the app sends back to `/api/whatif` unchanged (section 8.1), so it may hold a plain number such as `cut_pct`. |
| Merchants | Merchants are anonymised in the dataset. The core gives each merchant a label without digits that is stable for that customer, for example "Grocery store A" or "Restaurant B". The same label appears in cards, evidence and answer texts. |
| Ids | Opaque strings with a prefix: `CUST…` (customer, as in the dataset), `MRC-…` (merchant, as in the dataset), `ans_`, `conv_`, `card_`, `bill_`, `ev_` (evidence), `tx_` (transaction), `ins_` (insight). Ids `n1`, `n2`, … name numbers inside one answer. Do not parse ids. |
| Enum keys and labels | Every enum value the user sees (basket, category, profile, cadence, …) arrives as a stable `key` plus a separate localised `label`. Renaming a label never changes the key. |
| Baskets | `regular_essentials` ("Regular essentials"), `unexpected_necessities` ("Unexpected necessities"), `everyday_spending` ("Everyday spending"). These keys are shared with `docs/design/metrics.md`. |
| Categories | The 15 dataset categories, used as keys exactly as written: `Groceries`, `Restaurants`, `Transportation`, `Utilities`, `Entertainment`, `Health`, `Home & Tech`, `Housing`, `Lifestyle`, `Travel`, `Salary`, `Other Income`, `Invest Withdraw`, `Invest Deposit`, `Salary Sweep`. Following `metrics.md` section 0, the first 10 are spending. `Salary`, `Other Income` and `Invest Withdraw` are income. `Invest Deposit` is saving. `Salary Sweep` is a transfer, which is neither spending nor saving. |
| Age bands | `18-24`, `25-34`, `35-44`, `45-54`, `55-64`, `65-74`, `75+` (`metrics.md` section 6). |
| Time windows | "Typical" and monthly averages use the last 6 complete calendar months (`2026-04-01` to `2026-09-30` for today `2026-09-30`). "This week" for safe to spend is the 7 days after today. The core resolves every window into explicit `period` dates. |
| Unknown fields | The app ignores fields it does not know. The core may add fields in a minor version, and removing or renaming a field is a major version change. While the contract is a 0.x draft, a minor version may still remove or rename fields without a major bump; every such change is listed in the changelog. |
| CORS | The core allows the app's dev and production origins. |
| Internal endpoints | `GET /api/audit/{answer_id}` returns the audit record of one answer (design doc, section 9). It is for the team and the eval run, not for the app, and is not part of this contract. |

---

## 2. Shared objects

### 2.1 Number

Every number the coach shows is one of these objects. A number can always be traced back to its source through `evidence_ref`.

| Field | Type | Meaning |
|---|---|---|
| `value` | number | The value. Money is in euros, rounded to cents. Each value is rounded on its own, so parts shown next to a total, such as safe-to-spend components, can differ from it by 0.01. For `percent`, `12.5` means 12.5 %. |
| `unit` | enum | `eur`, `eur_per_day`, `eur_per_week`, `eur_per_month`, `eur_per_year`, `percent`, `percentile`, `count`, `days`, `months` |
| `period` | [Period](#22-period) | The time span the number describes. |
| `method` | string | The definition that produced the number, `<metric>.<output column>@<version>`. `<metric>` is a metric of `docs/design/metrics.md` named after its SQL file in `core/metrics/` (`recurring`, `baskets`, `safe_to_spend`, `what_if`, `spender_profile`, `peer_benchmark`, `store_price_index`), and the output column is the one listed there, for example `safe_to_spend.safe_to_spend_7d_eur@1`. Plain sums and counts that `metrics.md` does not define use `spending.*` and `evidence.*`, which are defined in the design document (section 6.2). Values the user typed in use `user_input@1`. |
| `evidence_ref` | string or null | Pass it to `GET /api/evidence/{ref}` to see how the number was built. One ref backs exactly one number (one `method` and `value`), and the same number shown in several places carries the same ref. It is `null` only for values the user typed in (`method` = `user_input@1`). |
| `label` | string | Short localised name, for example "Restaurants". |
| `display` | string | Localised formatted value, for example `€312.80` or `312,80 €`. A plus sign is never added. Negative values show a minus. |
| `id` | string | Present wherever a text refers to the number with a token (`/api/ask` answers, overview insights). It is the id used in the token, for example `n1`, and is unique within one answer or insight. |

<!-- example: shared.number -->
```json
{
  "value": 312.8,
  "unit": "eur",
  "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
  "method": "spending.total@1",
  "evidence_ref": "ev_r7t9v1x3z5b7",
  "label": "Restaurants",
  "display": "€312.80"
}
```

### 2.2 Period

`{ "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "label": "<localised>" }`. For a point in time (a balance today), `start` equals `end`. The core resolves presets such as "this week" or "last month" into explicit dates. The rules for that are in `docs/design/metrics.md`.

### 2.3 Comparison

Used by `metric` and `breakdown` cards.

| Field | Type | Meaning |
|---|---|---|
| `baseline` | Number | What we compare against, for example last month. |
| `change` | Number | Signed difference from the baseline. |
| `change_pct` | Number or null | Signed difference in percent. It is `null` when the baseline is 0. |
| `tone` | enum | `better`, `worse` or `neutral`. Use it for colour only; the rule is set per metric in `metrics.md`. |
| `label` | string | For example "vs August 2026". |

### 2.4 Text with number tokens

Coach texts (answers, insights) never contain digits typed by the AI model. Each number appears as a token `{{n1}}` that refers to a Number object delivered with the text. Tokens match the regex `\{\{(n[0-9]+)\}\}`.

- The app renders each token as a tappable chip that shows `display` and opens `GET /api/evidence/{evidence_ref}`.
- Every text that carries tokens also comes in a `text_rendered` version with the tokens already replaced. Use it for copying, sharing and screen readers.

---

## 3. Cards

Cards are built by the core from tool results, never written by the AI model. One renderer per `type` covers chat answers and the overview screen.

Fields common to all cards:

| Field | Type | Meaning |
|---|---|---|
| `card_id` | string | Unique within a response. |
| `type` | enum | `metric`, `breakdown`, `bills`, `peer`, `stores`, `profile`, `whatif` |
| `title` | string | Localised. |
| `subtitle` | string or null | Localised. |
| `evidence_ref` | string or null | Evidence for the card as a whole. |
| `estimate` | object or null | `{label, text}`. Set when the card shows an estimate rather than a fact: the safe-to-spend `metric` card, and the `bills` (pro rata amounts), `peer`, `whatif` and `stores` cards. The app must show `label` (for example "Estimate") and make `text` (the assumption in plain words) reachable. |
| `actions` | Action[] | Buttons, at most 2. See below. |

Card-specific fields:

| `type` | Fields | Example |
|---|---|---|
| `metric` | `status` (string or null); `primary` Number; `secondary` Number[]; `comparison` Comparison or null; `components` `{key, label, operation: "add" or "subtract", amount: Number}`[] (empty when not relevant). `status` is set only on the safe-to-spend card and is one of `ok`, `below_usual` or `nothing_free` (`metrics.md` section 3). Use it for tone and colour; it is `null` on every other `metric` card. For safe to spend (`metrics.md` section 3): the components `balance`, `bills_due`, `essentials_reserve`, `irregular_reserve` and `cushion` add up to the first secondary number, "Free until payday". Spread over the days to payday, it gives the balance limit (second secondary number). The primary number is the smaller of the balance limit and the budget limit (third secondary number). Each value is rounded to cents separately, so in real responses the components may differ from "Free until payday" by 0.01. The examples add up exactly. | `overview.response` (hero), `ask.json.response_fi` |
| `breakdown` | `display_hint` (`list`, `stacked_bar` or `time_series`); `total` Number; `comparison` Comparison or null; `items` `{key, label, amount: Number, share: Number or null, change: Number or null, flags: ("one_off" or "habit")[]}`[]. An item `key` is a category, basket, MCC group or month, or `other` for everything outside the top items. | `overview.response`, `ask.sse.card` |
| `bills` | `total` Number; `items` `{bill_id, label, category, cadence, status, status_label, typical_month: Number, last_paid, next_expected (date or null), due_until_payday: Number, evidence_ref}`[]. `cadence` is `monthly`, the only cadence in this data. `status` is one of `spread` (several payments a month, counted pro rata), `done_this_month`, `upcoming`, `late` or `skipped_this_month` (`metrics.md` section 2). Methods:
- `total` uses `safe_to_spend.bills_due_eur@1`, the per-customer total.
- Each `due_until_payday` uses `safe_to_spend.bill_due_eur@1`: one bill's term of that total. For a once-a-month bill that is its typical amount when it falls due before payday (the `bill_due` step of `core/metrics/03_safe_to_spend.sql`). For a `spread` bill it is the pro rata share computed in the `bills` step of the same file.
- **Pending:** `safe_to_spend.bill_due_eur` is not yet an output column of `03_safe_to_spend.sql`, which returns one row per customer. Issue #44 adds per-bill due amounts as a real output, and this method id names that future column.
- The items' `due_until_payday` add up to `total`. | `overview.response` |
| `peer` | `you`, `peer_median`, `peer_p25`, `peer_p75` (monthly averages), `percentile`, `vs_median` (all Number); `peer_group` `{level, label, size: Number, comparable: bool}`; `note`. `level` is `age_band+area3`, `age_band+city`, `age_band` or `all`: the most specific group with at least 20 other customers (`metrics.md` section 6). Without such a group, or for a customer whose salary is swept elsewhere, there is no peer card. Health is never benchmarked. | `card.peer` |
| `stores` | `items` `{merchant: {id, label}, is_s_group (bool or null), price_index: Number, price_index_ci95: {low: Number, high: Number} or null, differs_from_average: bool, visits: Number}`[]; `switch` `{status, status_label, home: {id, label}, alternative: {id, label} or null, home_spend_month: Number, ticket_gap: Number or null, estimated_saving: Number or null}`; `caveats` string[]. `switch.status` is `estimate`, `within_noise`, `already_lowest`, `not_measurable` or `no_alternative`. Only `estimate` carries a gap and a saving (`metrics.md` section 7). | `card.stores` |
| `profile` | `profile` `{key, label, description}`; `traits` `{key, label, note}`[]; `features` `{key, decides_label: bool, value: Number}`[]. `profile.key` is `not_enough_income_data`, `stretched`, `big_ticket`, `everyday_heavy`, `saver` or `steady`. `not_enough_income_data` means the account shows too little income for a verdict. `traits[].key` is any of `salary_moved_elsewhere`, `went_below_zero`, `regular_investor`, `weekend_spender` or `frequent_small_purchases`. `features[].key` is a profile feature from `metrics.md` section 5, using the exact names from there, for example `keep_rate`, `one_off_share`, `everyday_share_pct`, `everyday_weekend_pct` or `everyday_tx_month`. | `card.profile` |
| `whatif` | `result`: `{scenario, status, baseline_per_month, saving_per_month, saving_per_week, saving_per_year, one_off_excluded, regular_excluded, assumptions, caveats}`. That is the `POST /api/whatif` body without `customer_id`, `as_of` and `language`, and without `estimate` and `evidence_ref`, which sit on the card itself. `estimate` is always set. | `card.whatif` |

Actions:

| `type` | Fields | App behaviour |
|---|---|---|
| `open_evidence` | `label`, `evidence_ref` | Open the evidence sheet. |
| `ask` | `label`, `prompt` | Send `prompt` to `/api/ask` in the same conversation. |
| `open_whatif` | `label`, `scenario` (same shape as the `scenario` of a `/api/whatif` request, section 8.1) | Open the what-if screen with this scenario. |

<!-- example: card.peer -->
```json
{
  "card_id": "card_peer_01",
  "type": "peer",
  "title": "Restaurants: you and people like you",
  "subtitle": "Monthly average, April to September 2026",
  "evidence_ref": "ev_q1s3u5w7y9a1",
  "estimate": {
    "label": "Estimate",
    "text": "Compared with at least 20 other customers of your age band and area. Only group statistics are shown."
  },
  "you": {
    "value": 271.3, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "peer_benchmark.you_month_eur@1", "evidence_ref": "ev_q6s8u0w2y4a6",
    "label": "You", "display": "€271.30 a month"
  },
  "peer_median": {
    "value": 205.0, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "peer_benchmark.peer_median_month_eur@1", "evidence_ref": "ev_q1s3u5w7y9a1",
    "label": "Typical for your group", "display": "€205.00 a month"
  },
  "peer_p25": {
    "value": 140.0, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "peer_benchmark.peer_p25_month_eur@1", "evidence_ref": "ev_q2s4u6w8y0a2",
    "label": "Lower quarter", "display": "€140.00 a month"
  },
  "peer_p75": {
    "value": 290.0, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "peer_benchmark.peer_p75_month_eur@1", "evidence_ref": "ev_q3s5u7w9y1a3",
    "label": "Upper quarter", "display": "€290.00 a month"
  },
  "percentile": {
    "value": 72, "unit": "percentile",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "peer_benchmark.percentile@1", "evidence_ref": "ev_q4s6u8w0y2a4",
    "label": "Your position", "display": "72nd percentile"
  },
  "vs_median": {
    "value": 32.3, "unit": "percent",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "peer_benchmark.vs_median_pct@1", "evidence_ref": "ev_q7s9u1w3y5a7",
    "label": "Compared with typical", "display": "32.3% more"
  },
  "peer_group": {
    "level": "age_band+area3",
    "label": "Age 25-34, postal area 005",
    "size": {
      "value": 23, "unit": "count",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "peer_benchmark.peer_n@1", "evidence_ref": "ev_q5s7u9w1y3a5",
      "label": "Other people in the group", "display": "23"
    },
    "comparable": true
  },
  "note": "Only group statistics are shown, never another customer's transactions.",
  "actions": [
    { "type": "ask", "label": "How can I get closer to typical?", "prompt": "How can I spend less on restaurants?" }
  ]
}
```

<!-- example: card.stores -->
```json
{
  "card_id": "card_stores_01",
  "type": "stores",
  "title": "Your grocery stores",
  "subtitle": "Price level per visit, last 12 months",
  "evidence_ref": "ev_p5r7t9v1x3z5",
  "estimate": {
    "label": "Estimate",
    "text": "The data has receipt totals, not shelf prices. A higher level means people pay more per visit there, which mixes prices with basket size."
  },
  "items": [
    {
      "merchant": { "id": "MRC-GRO-0035", "label": "Grocery store A" },
      "is_s_group": null,
      "price_index": {
        "value": 3.1, "unit": "percent",
        "period": { "start": "2025-10-01", "end": "2026-09-30", "label": "Last 12 months" },
        "method": "store_price_index.index_pct@1", "evidence_ref": "ev_p5r7t9v1x3z5",
        "label": "Price level vs average", "display": "3.1%"
      },
      "price_index_ci95": {
        "low": {
          "value": -1.2, "unit": "percent",
          "period": { "start": "2025-10-01", "end": "2026-09-30", "label": "Last 12 months" },
          "method": "store_price_index.ci95_low_pct@1", "evidence_ref": "ev_p1c3i5l7o9w1",
          "label": "Lower bound", "display": "-1.2%"
        },
        "high": {
          "value": 7.4, "unit": "percent",
          "period": { "start": "2025-10-01", "end": "2026-09-30", "label": "Last 12 months" },
          "method": "store_price_index.ci95_high_pct@1", "evidence_ref": "ev_p2c4i6h8i0g2",
          "label": "Upper bound", "display": "7.4%"
        }
      },
      "differs_from_average": false,
      "visits": {
        "value": 4120, "unit": "count",
        "period": { "start": "2025-10-01", "end": "2026-09-30", "label": "Last 12 months" },
        "method": "store_price_index.n_visits@1", "evidence_ref": "ev_g9i1k3m5o7q9",
        "label": "Visits by all customers", "display": "4,120"
      }
    },
    {
      "merchant": { "id": "MRC-GRO-0012", "label": "Grocery store B" },
      "is_s_group": null,
      "price_index": {
        "value": -2.4, "unit": "percent",
        "period": { "start": "2025-10-01", "end": "2026-09-30", "label": "Last 12 months" },
        "method": "store_price_index.index_pct@1", "evidence_ref": "ev_p7r9t1v3x5z7",
        "label": "Price level vs average", "display": "-2.4%"
      },
      "price_index_ci95": {
        "low": {
          "value": -6.9, "unit": "percent",
          "period": { "start": "2025-10-01", "end": "2026-09-30", "label": "Last 12 months" },
          "method": "store_price_index.ci95_low_pct@1", "evidence_ref": "ev_p3c5i7l9o1w3",
          "label": "Lower bound", "display": "-6.9%"
        },
        "high": {
          "value": 2.1, "unit": "percent",
          "period": { "start": "2025-10-01", "end": "2026-09-30", "label": "Last 12 months" },
          "method": "store_price_index.ci95_high_pct@1", "evidence_ref": "ev_p4c6i8h0i2g4",
          "label": "Upper bound", "display": "2.1%"
        }
      },
      "differs_from_average": false,
      "visits": {
        "value": 1310, "unit": "count",
        "period": { "start": "2025-10-01", "end": "2026-09-30", "label": "Last 12 months" },
        "method": "store_price_index.n_visits@1", "evidence_ref": "ev_g0i2k4m6o8q0",
        "label": "Visits by all customers", "display": "1,310"
      }
    }
  ],
  "switch": {
    "status": "within_noise",
    "status_label": "The difference is within the noise, so no saving is claimed",
    "home": { "id": "MRC-GRO-0035", "label": "Grocery store A" },
    "alternative": { "id": "MRC-GRO-0012", "label": "Grocery store B" },
    "home_spend_month": {
      "value": 214.6, "unit": "eur_per_month",
      "period": { "start": "2025-10-01", "end": "2026-09-30", "label": "Last 12 months" },
      "method": "store_price_index.home_spend_month_eur@1", "evidence_ref": "ev_g7i9k1m3o5q7",
      "label": "You spend at your usual store", "display": "€214.60 a month"
    },
    "ticket_gap": null,
    "estimated_saving": null
  },
  "caveats": [
    "Price levels come from receipt totals of similar customers, not from shelf prices.",
    "Which stores belong to S-Group is a demo assumption."
  ],
  "actions": [
    { "type": "open_evidence", "label": "How is this estimated?", "evidence_ref": "ev_p5r7t9v1x3z5" }
  ]
}
```

<!-- example: card.profile -->
```json
{
  "card_id": "card_profile_01",
  "type": "profile",
  "title": "What kind of spender are you?",
  "subtitle": "Based on April to September 2026",
  "evidence_ref": "ev_x1z3b5d7f9h1",
  "estimate": null,
  "profile": {
    "key": "everyday_heavy",
    "label": "Everyday spender",
    "description": "A large share of your money goes to everyday spending, such as eating out and entertainment."
  },
  "traits": [
    {
      "key": "weekend_spender",
      "label": "Weekend spender",
      "note": "Much of your everyday spending happens at weekends."
    },
    {
      "key": "frequent_small_purchases",
      "label": "Many small purchases",
      "note": "You make many small everyday purchases each month."
    }
  ],
  "features": [
    {
      "key": "everyday_share_pct",
      "decides_label": true,
      "value": {
        "value": 31.2, "unit": "percent",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "spender_profile.everyday_share_pct@1", "evidence_ref": "ev_x2z4b6d8f0h2",
        "label": "Everyday spending, share of spending", "display": "31.2%"
      }
    },
    {
      "key": "keep_rate",
      "decides_label": false,
      "value": {
        "value": 9.6, "unit": "percent",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "spender_profile.keep_rate_pct@1", "evidence_ref": "ev_x3z5b7d9f1h3",
        "label": "Kept from income", "display": "9.6%"
      }
    },
    {
      "key": "everyday_weekend_pct",
      "decides_label": false,
      "value": {
        "value": 47.5, "unit": "percent",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "spender_profile.everyday_weekend_pct@1", "evidence_ref": "ev_x4z6b8d0f2h4",
        "label": "Everyday spending at weekends", "display": "47.5%"
      }
    },
    {
      "key": "everyday_tx_month",
      "decides_label": false,
      "value": {
        "value": 14.2, "unit": "count",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "spender_profile.everyday_tx_month@1", "evidence_ref": "ev_x5z7b9d1f3h5",
        "label": "Everyday purchases a month", "display": "14.2 a month"
      }
    }
  ],
  "actions": []
}
```

<!-- example: card.whatif -->
```json
{
  "card_id": "card_whatif_01",
  "type": "whatif",
  "title": "Spend 20% less on restaurants",
  "subtitle": "Based on your last 6 full months",
  "evidence_ref": "ev_w3y5a7c9e1g3",
  "estimate": { "label": "Estimate", "text": "Average of your last 6 full months (one-off purchases left out), cut by 20%." },
  "result": {
    "scenario": {
      "selection": { "kind": "category", "value": "Restaurants" },
      "cut_pct": {
        "value": 20, "unit": "percent",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "user_input@1", "evidence_ref": null,
        "label": "Cut you chose", "display": "20%"
      },
      "label": "Spend 20% less on restaurants"
    },
    "status": "estimate",
    "baseline_per_month": {
      "value": 268.4, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "what_if.baseline_month_eur@1", "evidence_ref": "ev_w1y3a5c7e9g1",
      "label": "Restaurants in a typical month", "display": "€268.40 a month"
    },
    "saving_per_month": {
      "value": 53.68, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "what_if.saving_month_eur@1", "evidence_ref": "ev_w3y5a7c9e1g3",
      "label": "You would save", "display": "€53.68 a month"
    },
    "saving_per_week": {
      "value": 12.35, "unit": "eur_per_week",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "what_if.saving_week_eur@1", "evidence_ref": "ev_w5y7a9c1e3g5",
      "label": "Per week", "display": "€12.35 a week"
    },
    "saving_per_year": {
      "value": 644.16, "unit": "eur_per_year",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "what_if.saving_year_eur@1", "evidence_ref": "ev_w4y6a8c0e2g4",
      "label": "Per year", "display": "€644.16 a year"
    },
    "one_off_excluded": {
      "value": 38.5, "unit": "eur",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "what_if.one_off_excluded_eur@1", "evidence_ref": "ev_w6y8a0c2e4g6",
      "label": "One-off purchases left out", "display": "€38.50"
    },
    "regular_excluded": {
      "value": 0.0, "unit": "eur",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "what_if.regular_excluded_eur@1", "evidence_ref": "ev_w7y9a1c3e5g7",
      "label": "Regular essentials left out", "display": "€0.00"
    },
    "assumptions": [
      "Average of your last 6 full months (one-off purchases left out), cut by 20%.",
      "The rest of your spending stays as it is."
    ],
    "caveats": ["This is an estimate, not a promise. Prices and habits change."]
  },
  "actions": [
    { "type": "open_evidence", "label": "How is this calculated?", "evidence_ref": "ev_w3y5a7c9e1g3" }
  ]
}
```

---

## 4. Errors

Every error response has the same envelope, and the `error` event inside the `/api/ask` stream uses it too. The app shows `message` (already localised) and offers a retry when `retryable` is true.

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid_request` | Malformed body or a bad parameter. |
| 404 | `customer_not_found` | Unknown `customer_id`. |
| 404 | `evidence_not_found` | Unknown or expired `ref`. |
| 403 | `evidence_forbidden` | The evidence belongs to a different customer. |
| 422 | `invalid_scenario` | The what-if scenario cannot be computed, for example an unknown bill. |
| 429 | `rate_limited` | Too many requests. Retry after the `Retry-After` header. |
| 503 | `data_unavailable` | The database cannot be reached or is too slow. |
| 503 | `llm_unavailable` | Only when there is no fallback answer at all. Normally `/api/ask` answers with a template instead (section 7.5). |
| 500 | `internal` | Anything else. |

<!-- example: error.response -->
```json
{
  "error": {
    "code": "customer_not_found",
    "message": "We couldn't find this customer.",
    "retryable": false
  }
}
```

---

## 5. `GET /api/personas`

Lists the demo customers the app can switch between. These are curated customers from the synthetic dataset. Display names are invented and labelled as demo personas. `age_band` uses the age bands from section 1, and `profile.key` uses the profile keys of the `profile` card (section 3).

**Request:** `GET /api/personas?lang=en`

<!-- example: personas.response -->
```json
{
  "as_of": "2026-09-30",
  "language": "en",
  "personas": [
    {
      "customer_id": "CUST00042",
      "display_name": "Aino",
      "age_band": "25-34",
      "postal_area": { "code": "00530", "label": "Helsinki 00530" },
      "profile": { "key": "everyday_heavy", "label": "Everyday spender" },
      "tagline": "Steady salary, rents in Helsinki, eats out often.",
      "default_language": "en"
    },
    {
      "customer_id": "CUST00017",
      "display_name": "Mikko",
      "age_band": "45-54",
      "postal_area": { "code": "02100", "label": "Espoo 02100" },
      "profile": { "key": "steady", "label": "Steady" },
      "tagline": "Predictable bills and a regular investment deposit.",
      "default_language": "fi"
    },
    {
      "customer_id": "CUST00088",
      "display_name": "Leena",
      "age_band": "18-24",
      "postal_area": { "code": "00100", "label": "Helsinki 00100" },
      "profile": { "key": "stretched", "label": "Stretched" },
      "tagline": "Part-time income; some months cost more than comes in.",
      "default_language": "en"
    }
  ]
}
```

---

## 6. `GET /api/overview/{customer_id}`

The home screen. It is fully deterministic: no AI model is called, and it reads precomputed tables only, so it is fast and safe to call on every app open.

**Request:** `GET /api/overview/CUST00042?lang=en`

**Response fields:**
- `customer_id`, `as_of`, `language`, `greeting`.
- `ai_disclosure`: show it on the first chat screen.
- `hero`: a `metric` card, safe to spend in the next 7 days (`metrics.md` section 3; how its components work is in section 3 of this contract). Its `status` field carries the metrics status (`ok`, `below_usual` or `nothing_free`). The subtitle carries the period, for example "1 to 7 October", not the status.
- `cards`: Card[] (spending baskets, bills before payday, and more later).
- `insights`: Insight[].
- `suggested_questions`: string[], sent to `/api/ask` when tapped. These are the partner's four questions.

An Insight is `{insight_id, kind, title, text, text_rendered, numbers, estimate, action}`:
- `kind` is one of `habit_trend`, `one_off`, `bill_change`, `store_saving`, `peer_gap`, `low_safe_to_spend`. `store_saving` appears only when the store switch status is `estimate`.
- `text` uses number tokens (section 2.4), and `numbers` maps each token id to its Number object.
- `estimate` works as on cards.
- `action` is one Action or null.

<!-- example: overview.response -->
```json
{
  "customer_id": "CUST00042",
  "as_of": "2026-09-30",
  "language": "en",
  "greeting": "Hi Aino",
  "ai_disclosure": "Explanations are written by AI. The numbers are calculated from your transactions.",
  "hero": {
    "card_id": "card_sts_01",
    "type": "metric",
    "title": "Safe to spend in the next 7 days",
    "subtitle": "1 to 7 October",
    "evidence_ref": "ev_s2t4w6y8a0c2",
    "estimate": {
      "label": "Estimate",
      "text": "Your balance minus bills, usual essentials and a small cushion until payday, spread over the days to payday. It is also capped by your usual monthly budget."
    },
    "status": "ok",
    "primary": {
      "value": 184.68, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
      "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_s2t4w6y8a0c2",
      "label": "Safe to spend", "display": "€184.68"
    },
    "secondary": [
      {
        "value": 395.74, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_s4t6w8y0a2c4",
        "label": "Free until payday", "display": "€395.74"
      },
      {
        "value": 184.68, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.balance_limit_7d_eur@1", "evidence_ref": "ev_s3t5w7y9a1c3",
        "label": "Your balance allows", "display": "€184.68"
      },
      {
        "value": 248.5, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.budget_limit_7d_eur@1", "evidence_ref": "ev_s5t7w9y1a3c5",
        "label": "Your monthly budget allows", "display": "€248.50"
      }
    ],
    "comparison": null,
    "components": [
      {
        "key": "balance",
        "label": "Money on your account",
        "operation": "add",
        "amount": {
          "value": 1640.15, "unit": "eur",
          "period": { "start": "2026-09-30", "end": "2026-09-30", "label": "30 Sep 2026" },
          "method": "safe_to_spend.balance_eur@1", "evidence_ref": "ev_b4l6n8p0r2t4",
          "label": "Balance", "display": "€1,640.15"
        }
      },
      {
        "key": "bills_due",
        "label": "Bills due before payday",
        "operation": "subtract",
        "amount": {
          "value": 842.19, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.bills_due_eur@1", "evidence_ref": "ev_u6b8d0f2h4j6",
          "label": "Bills before payday", "display": "€842.19"
        }
      },
      {
        "key": "essentials_reserve",
        "label": "Usual essentials until payday",
        "operation": "subtract",
        "amount": {
          "value": 134.76, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.essentials_reserve_eur@1", "evidence_ref": "ev_e1s3r5v7e9a1",
          "label": "Essentials reserve", "display": "€134.76"
        }
      },
      {
        "key": "irregular_reserve",
        "label": "Reserve for unexpected necessities",
        "operation": "subtract",
        "amount": {
          "value": 167.46, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_i1r3r5v7e9a2",
          "label": "Irregular reserve", "display": "€167.46"
        }
      },
      {
        "key": "cushion",
        "label": "Cushion",
        "operation": "subtract",
        "amount": {
          "value": 100.0, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.cushion_eur@1", "evidence_ref": "ev_f8h0j2l4n6p8",
          "label": "Cushion", "display": "€100.00"
        }
      }
    ],
    "actions": [
      { "type": "open_evidence", "label": "How is this calculated?", "evidence_ref": "ev_s2t4w6y8a0c2" },
      { "type": "ask", "label": "Can I afford a dinner out?", "prompt": "Can I afford a dinner out this week?" }
    ]
  },
  "cards": [
    {
      "card_id": "card_baskets_01",
      "type": "breakdown",
      "title": "Where your money goes in a typical month",
      "subtitle": "Monthly average, April to September 2026",
      "evidence_ref": "ev_k4m6p8r0t2v4",
      "estimate": null,
      "display_hint": "stacked_bar",
      "total": {
        "value": 2211.01, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "spender_profile.spend_month_eur@1", "evidence_ref": "ev_k4m6p8r0t2v4",
        "label": "Total spending", "display": "€2,211.01 a month"
      },
      "comparison": null,
      "items": [
        {
          "key": "regular_essentials",
          "label": "Regular essentials",
          "amount": {
            "value": 1180.21, "unit": "eur_per_month",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_br1a3c5e7g9i",
            "label": "Regular essentials", "display": "€1,180.21 a month"
          },
          "share": {
            "value": 53.4, "unit": "percent",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.share_pct@1", "evidence_ref": "ev_bs1a3c5e7g9i",
            "label": "Share of spending", "display": "53.4%"
          },
          "change": null,
          "flags": []
        },
        {
          "key": "unexpected_necessities",
          "label": "Unexpected necessities",
          "amount": {
            "value": 340.5, "unit": "eur_per_month",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_bi2b4d6f8h0j",
            "label": "Unexpected necessities", "display": "€340.50 a month"
          },
          "share": {
            "value": 15.4, "unit": "percent",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.share_pct@1", "evidence_ref": "ev_bt2b4d6f8h0j",
            "label": "Share of spending", "display": "15.4%"
          },
          "change": null,
          "flags": []
        },
        {
          "key": "everyday_spending",
          "label": "Everyday spending",
          "amount": {
            "value": 690.3, "unit": "eur_per_month",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_bl3c5e7g9i1k",
            "label": "Everyday spending", "display": "€690.30 a month"
          },
          "share": {
            "value": 31.2, "unit": "percent",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.share_pct@1", "evidence_ref": "ev_bu3c5e7g9i1k",
            "label": "Share of spending", "display": "31.2%"
          },
          "change": null,
          "flags": []
        }
      ],
      "actions": [
        { "type": "ask", "label": "What is in everyday spending?", "prompt": "What is in my everyday spending?" }
      ]
    },
    {
      "card_id": "card_bills_01",
      "type": "bills",
      "title": "Bills before payday",
      "subtitle": "1 to 15 October",
      "evidence_ref": "ev_u6b8d0f2h4j6",
      "estimate": {
        "label": "Estimate",
        "text": "Utilities are paid about three times a month, so the amount until payday is pro rata."
      },
      "total": {
        "value": 842.19, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.bills_due_eur@1", "evidence_ref": "ev_u6b8d0f2h4j6",
        "label": "Bills before payday", "display": "€842.19"
      },
      "items": [
        {
          "bill_id": "bill_housing_payment",
          "label": "Housing",
          "category": "Housing",
          "cadence": "monthly",
          "status": "done_this_month",
          "status_label": "Paid this month, usually around the 1st",
          "typical_month": {
            "value": 780.0, "unit": "eur_per_month",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "recurring.typical_month_eur@1", "evidence_ref": "ev_h1o3u5s7e9a1",
            "label": "Usual amount", "display": "€780.00 a month"
          },
          "last_paid": "2026-09-01",
          "next_expected": "2026-10-01",
          "due_until_payday": {
            "value": 780.0, "unit": "eur",
            "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
            "method": "safe_to_spend.bill_due_eur@1", "evidence_ref": "ev_h5o7u9s1e3a5",
            "label": "Due before payday", "display": "€780.00"
          },
          "evidence_ref": "ev_h1o3u5s7e9a1"
        },
        {
          "bill_id": "bill_utilities_payment",
          "label": "Utilities",
          "category": "Utilities",
          "cadence": "monthly",
          "status": "spread",
          "status_label": "About three payments a month",
          "typical_month": {
            "value": 126.2, "unit": "eur_per_month",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "recurring.typical_month_eur@1", "evidence_ref": "ev_h2o4u6s8e0a2",
            "label": "Usual amount", "display": "€126.20 a month"
          },
          "last_paid": "2026-09-27",
          "next_expected": null,
          "due_until_payday": {
            "value": 62.19, "unit": "eur",
            "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
            "method": "safe_to_spend.bill_due_eur@1", "evidence_ref": "ev_h6o8u0s2e4a6",
            "label": "Due before payday, pro rata", "display": "€62.19"
          },
          "evidence_ref": "ev_h2o4u6s8e0a2"
        }
      ],
      "actions": [
        { "type": "ask", "label": "Which bills grew this year?", "prompt": "Which of my bills have grown this year?" }
      ]
    }
  ],
  "insights": [
    {
      "insight_id": "ins_rest_01",
      "kind": "habit_trend",
      "title": "Eating out is up",
      "text": "You spent {{n1}} on restaurants in September, {{n2}} more than in August.",
      "text_rendered": "You spent €312.80 on restaurants in September, €91.70 more than in August.",
      "numbers": {
        "n1": {
          "id": "n1", "value": 312.8, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
          "method": "spending.total@1", "evidence_ref": "ev_r7t9v1x3z5b7",
          "label": "Restaurants", "display": "€312.80"
        },
        "n2": {
          "id": "n2", "value": 91.7, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
          "method": "spending.change@1", "evidence_ref": "ev_r8t0v2x4z6b8",
          "label": "Change vs August", "display": "€91.70"
        }
      },
      "estimate": null,
      "action": {
        "type": "ask",
        "label": "How can I spend less on eating out?",
        "prompt": "How can I spend less on restaurants?"
      }
    },
    {
      "insight_id": "ins_oneoff_01",
      "kind": "one_off",
      "title": "A one-off in September",
      "text": "Travel cost {{n1}} in September. It was a one-off, so it is left out of your typical month.",
      "text_rendered": "Travel cost €240.00 in September. It was a one-off, so it is left out of your typical month.",
      "numbers": {
        "n1": {
          "id": "n1", "value": 240.0, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
          "method": "spending.total@1", "evidence_ref": "ev_t2v4x6z8b0d2",
          "label": "Travel", "display": "€240.00"
        }
      },
      "estimate": null,
      "action": {
        "type": "ask",
        "label": "What does a typical month look like?",
        "prompt": "What does my typical month look like?"
      }
    }
  ],
  "suggested_questions": [
    "Where did my money go?",
    "What kind of spender am I?",
    "What can I safely spend this week?",
    "How could I save more?"
  ]
}
```

---

## 7. `POST /api/ask`

Ask the coach a question. The core runs deterministic tools, builds cards from their results and sends an explanation. The AI model never sees raw transactions and never types a number (see the design document, sections 5 and 7).

The partner's four questions are the main intents, and the app should offer them as starting points:
- "Where did my money go?"
- "What kind of spender am I?"
- "What can I safely spend this week?"
- "How could I save more?"

### 7.1 Request

| Field | Type | Meaning |
|---|---|---|
| `customer_id` | string | Persona from `/api/personas`. |
| `conversation_id` | string or null | `null` starts a new conversation. Send the id from `meta` to ask a follow-up. The server keeps the history (last 6 turns, 30 minutes). The app does not resend it. A conversation belongs to one customer. An id that is unknown, expired or belongs to another customer starts a new conversation: `meta` carries the new id, `done.warnings` contains `conversation_reset`, and earlier tool results are never reused. |
| `message` | string | The question, at most 500 characters. |
| `language` | `en`, `fi` or `auto` | `auto` detects the language from the message. |

The `Accept` header chooses the response format:

- `text/event-stream` gives a stream of server-sent events (section 7.2). This is the main path.
- `application/json` gives one JSON object with the final result (section 7.4). It is the easiest to mock and to test.

<!-- example: ask.request -->
```json
{
  "customer_id": "CUST00042",
  "conversation_id": null,
  "message": "Where did my money go?",
  "language": "auto"
}
```

A follow-up in the same conversation:

<!-- example: ask.request_followup -->
```json
{
  "customer_id": "CUST00042",
  "conversation_id": "conv_4h8j2n6p",
  "message": "What if I spend 20% less on restaurants?",
  "language": "auto"
}
```

**Errors before the stream.** The core validates the request before it opens the stream. These failures come back as a plain HTTP error with the envelope from section 4, never as a stream:
- a bad body or a message over 500 characters: 400 `invalid_request`;
- an unknown customer: 404 `customer_not_found`;
- too many requests: 429 `rate_limited`.

Once the stream is open (HTTP 200), a failure arrives as an `error` event with the same envelope.

### 7.2 Stream events

The response is `Content-Type: text/event-stream`. Each event is an `event:` line and one `data:` line with a single-line JSON object, followed by a blank line. The server sends a comment line `: ping` every 10 seconds while it works. The stream ends after `done` or `error`.

The browser `EventSource` API only supports GET, so read the stream with `fetch()` and a `ReadableStream` reader, and split events on blank lines.

| Event | Sent | Payload |
|---|---|---|
| `meta` | Always first, once | `answer_id`, `conversation_id`, `language`, `as_of` |
| `status` | 0 or more times | `stage` (`understanding`, `tool` or `writing`), `tool` (tool name or null), `label` (localised progress text) |
| `card` | 0 to 3 times, as soon as a tool finishes | `card` (section 3) |
| `numbers` | Before the first `delta` that uses them | `numbers`: a map from id to Number object |
| `delta` | 1 or more times | `text`: the next piece of the answer, with number tokens. A token is never split across two deltas. Append the pieces in order. In version 0.1 the core validates the whole answer first and then sends it sentence by sentence. Finer streaming may come later without a contract change. |
| `done` | Last, once, on success | `answer_id`, `outcome`, `text` (full, with tokens), `text_rendered`, `cited` (number ids used), `follow_ups` (string[]), `lesson` (`{key, title, text}` or null), `refusal` (`{kind, label}` or null), `clarify` (`{question, options}` or null), `warnings` (string[] of codes, see below) |
| `error` | Last, once, on failure | `error`: `{code, message, retryable}`, the same envelope as an HTTP error (section 4) |

`outcome` is one of:
- `answered`: a normal answer.
- `clarify`: the coach asks a question back.
- `refused`: out of scope; see `refusal.kind`.
- `fallback`: the AI model was unavailable, so the text is a template built from the tool results.

`refusal.kind` is one of `investment_advice`, `credit_decision` (for example "Will the bank approve my mortgage?"), `out_of_scope`, `other_person_data` or `unsafe`.

`clarify` is set only when `outcome` is `clarify`:
- `question` repeats the text.
- `options` holds up to 3 short answers. The app shows them as chips, and a tap sends the option's text as the next message in the same conversation.

`warnings` holds codes the app may show as a small note:
- `llm_unavailable`: the text is a template.
- `tool_failed`: some data could not be computed, and the answer says which.
- `period_clamped`: the period was moved to fit the data window.
- `conversation_reset`: a new conversation was started.

The events of the example answer, one by one:

<!-- example: ask.sse.meta -->
```json
{ "answer_id": "ans_7f3k9q2m", "conversation_id": "conv_4h8j2n6p", "language": "en", "as_of": "2026-09-30" }
```

<!-- example: ask.sse.status -->
```json
{ "stage": "tool", "tool": "get_spending", "label": "Looking at where your money went in September" }
```

<!-- example: ask.sse.card -->
```json
{
  "card": {
    "card_id": "card_ans7f_01",
    "type": "breakdown",
    "title": "September compared with August",
    "subtitle": "Biggest changes by category",
    "evidence_ref": "ev_k3m5p7r9t1v3",
    "estimate": null,
    "display_hint": "list",
    "total": {
      "id": "n1", "value": 2315.6, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
      "method": "spending.total@1", "evidence_ref": "ev_k3m5p7r9t1v3",
      "label": "Total spending", "display": "€2,315.60"
    },
    "comparison": {
      "baseline": {
        "id": "n2", "value": 1948.2, "unit": "eur",
        "period": { "start": "2026-08-01", "end": "2026-08-31", "label": "August 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_a2c4e6g8i0k2",
        "label": "August spending", "display": "€1,948.20"
      },
      "change": {
        "id": "n3", "value": 367.4, "unit": "eur",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
        "method": "spending.change@1", "evidence_ref": "ev_m3o5q7s9u1w3",
        "label": "Change vs August", "display": "€367.40"
      },
      "change_pct": {
        "id": "n4", "value": 18.9, "unit": "percent",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
        "method": "spending.change_pct@1", "evidence_ref": "ev_m4o6q8s0u2w4",
        "label": "Change vs August", "display": "18.9%"
      },
      "tone": "worse",
      "label": "vs August 2026"
    },
    "items": [
      {
        "key": "Travel",
        "label": "Travel",
        "amount": {
          "id": "n5", "value": 240.0, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
          "method": "spending.total@1", "evidence_ref": "ev_t2v4x6z8b0d2",
          "label": "Travel", "display": "€240.00"
        },
        "share": null,
        "change": {
          "id": "n6", "value": 240.0, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
          "method": "spending.change@1", "evidence_ref": "ev_t3v5x7z9b1d3",
          "label": "Travel, change vs August", "display": "€240.00"
        },
        "flags": ["one_off"]
      },
      {
        "key": "Restaurants",
        "label": "Restaurants",
        "amount": {
          "id": "n7", "value": 312.8, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
          "method": "spending.total@1", "evidence_ref": "ev_r7t9v1x3z5b7",
          "label": "Restaurants", "display": "€312.80"
        },
        "share": null,
        "change": {
          "id": "n8", "value": 91.7, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
          "method": "spending.change@1", "evidence_ref": "ev_r8t0v2x4z6b8",
          "label": "Restaurants, change vs August", "display": "€91.70"
        },
        "flags": ["habit"]
      },
      {
        "key": "other",
        "label": "Everything else",
        "amount": {
          "id": "n9", "value": 1762.8, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
          "method": "spending.total@1", "evidence_ref": "ev_o1q3s5u7w9y1",
          "label": "Everything else", "display": "€1,762.80"
        },
        "share": null,
        "change": {
          "id": "n10", "value": 35.7, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
          "method": "spending.change@1", "evidence_ref": "ev_o2q4s6u8w0y2",
          "label": "Everything else, change vs August", "display": "€35.70"
        },
        "flags": []
      }
    ],
    "actions": [
      { "type": "open_evidence", "label": "See September transactions", "evidence_ref": "ev_k3m5p7r9t1v3" },
      {
        "type": "open_whatif",
        "label": "Try 20% less on restaurants",
        "scenario": { "selection": { "kind": "category", "value": "Restaurants" }, "cut_pct": 20 }
      }
    ]
  }
}
```

<!-- example: ask.sse.numbers_1 -->
```json
{
  "numbers": {
    "n1": {
      "id": "n1", "value": 2315.6, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
      "method": "spending.total@1", "evidence_ref": "ev_k3m5p7r9t1v3",
      "label": "Total spending", "display": "€2,315.60"
    },
    "n3": {
      "id": "n3", "value": 367.4, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
      "method": "spending.change@1", "evidence_ref": "ev_m3o5q7s9u1w3",
      "label": "Change vs August", "display": "€367.40"
    }
  }
}
```

<!-- example: ask.sse.delta_1 -->
```json
{ "text": "September cost {{n1}}, which is {{n3}} more than August. " }
```

<!-- example: ask.sse.numbers_2 -->
```json
{
  "numbers": {
    "n5": {
      "id": "n5", "value": 240.0, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
      "method": "spending.total@1", "evidence_ref": "ev_t2v4x6z8b0d2",
      "label": "Travel", "display": "€240.00"
    },
    "n8": {
      "id": "n8", "value": 91.7, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
      "method": "spending.change@1", "evidence_ref": "ev_r8t0v2x4z6b8",
      "label": "Restaurants, change vs August", "display": "€91.70"
    }
  }
}
```

<!-- example: ask.sse.delta_2 -->
```json
{ "text": "Most of the increase is Travel at {{n5}}, which looks like a one-off, and Restaurants, up {{n8}}. " }
```

<!-- example: ask.sse.delta_3 -->
```json
{ "text": "A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust." }
```

<!-- example: ask.sse.done -->
```json
{
  "answer_id": "ans_7f3k9q2m",
  "outcome": "answered",
  "text": "September cost {{n1}}, which is {{n3}} more than August. Most of the increase is Travel at {{n5}}, which looks like a one-off, and Restaurants, up {{n8}}. A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust.",
  "text_rendered": "September cost €2,315.60, which is €367.40 more than August. Most of the increase is Travel at €240.00, which looks like a one-off, and Restaurants, up €91.70. A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust.",
  "cited": ["n1", "n3", "n5", "n8"],
  "follow_ups": [
    "What if I spend 20% less on restaurants?",
    "How could I save more?",
    "What can I safely spend this week?"
  ],
  "lesson": {
    "key": "one_off_vs_habit",
    "title": "One-offs and habits",
    "text": "A one-off cost, like a trip, shows up once. A habit, like eating out, repeats every month, so a small change there adds up over a year."
  },
  "refusal": null,
  "clarify": null,
  "warnings": []
}
```

### 7.3 The full stream

The same answer as it travels on the wire. This text is generated from the payloads above.

<!-- example: ask.sse.stream -->
```text
event: meta
data: {"answer_id":"ans_7f3k9q2m","conversation_id":"conv_4h8j2n6p","language":"en","as_of":"2026-09-30"}

event: status
data: {"stage":"tool","tool":"get_spending","label":"Looking at where your money went in September"}

event: card
data: {"card":{"card_id":"card_ans7f_01","type":"breakdown","title":"September compared with August","subtitle":"Biggest changes by category","evidence_ref":"ev_k3m5p7r9t1v3","estimate":null,"display_hint":"list","total":{"id":"n1","value":2315.6,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending.total@1","evidence_ref":"ev_k3m5p7r9t1v3","label":"Total spending","display":"€2,315.60"},"comparison":{"baseline":{"id":"n2","value":1948.2,"unit":"eur","period":{"start":"2026-08-01","end":"2026-08-31","label":"August 2026"},"method":"spending.total@1","evidence_ref":"ev_a2c4e6g8i0k2","label":"August spending","display":"€1,948.20"},"change":{"id":"n3","value":367.4,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending.change@1","evidence_ref":"ev_m3o5q7s9u1w3","label":"Change vs August","display":"€367.40"},"change_pct":{"id":"n4","value":18.9,"unit":"percent","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending.change_pct@1","evidence_ref":"ev_m4o6q8s0u2w4","label":"Change vs August","display":"18.9%"},"tone":"worse","label":"vs August 2026"},"items":[{"key":"Travel","label":"Travel","amount":{"id":"n5","value":240.0,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending.total@1","evidence_ref":"ev_t2v4x6z8b0d2","label":"Travel","display":"€240.00"},"share":null,"change":{"id":"n6","value":240.0,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending.change@1","evidence_ref":"ev_t3v5x7z9b1d3","label":"Travel, change vs August","display":"€240.00"},"flags":["one_off"]},{"key":"Restaurants","label":"Restaurants","amount":{"id":"n7","value":312.8,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending.total@1","evidence_ref":"ev_r7t9v1x3z5b7","label":"Restaurants","display":"€312.80"},"share":null,"change":{"id":"n8","value":91.7,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending.change@1","evidence_ref":"ev_r8t0v2x4z6b8","label":"Restaurants, change vs August","display":"€91.70"},"flags":["habit"]},{"key":"other","label":"Everything else","amount":{"id":"n9","value":1762.8,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending.total@1","evidence_ref":"ev_o1q3s5u7w9y1","label":"Everything else","display":"€1,762.80"},"share":null,"change":{"id":"n10","value":35.7,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending.change@1","evidence_ref":"ev_o2q4s6u8w0y2","label":"Everything else, change vs August","display":"€35.70"},"flags":[]}],"actions":[{"type":"open_evidence","label":"See September transactions","evidence_ref":"ev_k3m5p7r9t1v3"},{"type":"open_whatif","label":"Try 20% less on restaurants","scenario":{"selection":{"kind":"category","value":"Restaurants"},"cut_pct":20}}]}}

event: numbers
data: {"numbers":{"n1":{"id":"n1","value":2315.6,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending.total@1","evidence_ref":"ev_k3m5p7r9t1v3","label":"Total spending","display":"€2,315.60"},"n3":{"id":"n3","value":367.4,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending.change@1","evidence_ref":"ev_m3o5q7s9u1w3","label":"Change vs August","display":"€367.40"}}}

event: delta
data: {"text":"September cost {{n1}}, which is {{n3}} more than August. "}

event: numbers
data: {"numbers":{"n5":{"id":"n5","value":240.0,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending.total@1","evidence_ref":"ev_t2v4x6z8b0d2","label":"Travel","display":"€240.00"},"n8":{"id":"n8","value":91.7,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending.change@1","evidence_ref":"ev_r8t0v2x4z6b8","label":"Restaurants, change vs August","display":"€91.70"}}}

event: delta
data: {"text":"Most of the increase is Travel at {{n5}}, which looks like a one-off, and Restaurants, up {{n8}}. "}

event: delta
data: {"text":"A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust."}

event: done
data: {"answer_id":"ans_7f3k9q2m","outcome":"answered","text":"September cost {{n1}}, which is {{n3}} more than August. Most of the increase is Travel at {{n5}}, which looks like a one-off, and Restaurants, up {{n8}}. A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust.","text_rendered":"September cost €2,315.60, which is €367.40 more than August. Most of the increase is Travel at €240.00, which looks like a one-off, and Restaurants, up €91.70. A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust.","cited":["n1","n3","n5","n8"],"follow_ups":["What if I spend 20% less on restaurants?","How could I save more?","What can I safely spend this week?"],"lesson":{"key":"one_off_vs_habit","title":"One-offs and habits","text":"A one-off cost, like a trip, shows up once. A habit, like eating out, repeats every month, so a small change there adds up over a year."},"refusal":null,"clarify":null,"warnings":[]}
```

A stream that fails before any answer:

<!-- example: ask.sse.stream_error -->
```text
event: meta
data: {"answer_id":"ans_1x3z5b7d","conversation_id":"conv_4h8j2n6p","language":"en","as_of":"2026-09-30"}

event: status
data: {"stage":"understanding","tool":null,"label":"Reading your question"}

: ping

event: error
data: {"error":{"code":"data_unavailable","message":"Your data can't be loaded right now. Please try again in a minute.","retryable":true}}
```

<!-- example: ask.sse.error -->
```json
{ "error": { "code": "data_unavailable", "message": "Your data can't be loaded right now. Please try again in a minute.", "retryable": true } }
```

### 7.4 Non-streaming response

With `Accept: application/json` the response is a single object with the fields of `meta` and `done`, plus `numbers` (every cited number) and `cards`.

A question in Finnish (`language: "auto"` detects `fi`):

<!-- example: ask.json.request_fi -->
```json
{
  "customer_id": "CUST00042",
  "conversation_id": null,
  "message": "Paljonko käytin ruokaan syyskuussa?",
  "language": "auto"
}
```

<!-- example: ask.json.response_fi -->
```json
{
  "answer_id": "ans_2b6d8f1h",
  "conversation_id": "conv_9k3m5p7r",
  "language": "fi",
  "as_of": "2026-09-30",
  "outcome": "answered",
  "text": "Käytit syyskuussa ruokaostoksiin {{n1}}, eli {{n3}} enemmän kuin elokuussa. Ero on pieni, joten ruokamenosi ovat pysyneet melko tasaisina.",
  "text_rendered": "Käytit syyskuussa ruokaostoksiin 401,50 €, eli 35,70 € enemmän kuin elokuussa. Ero on pieni, joten ruokamenosi ovat pysyneet melko tasaisina.",
  "cited": ["n1", "n3"],
  "numbers": {
    "n1": {
      "id": "n1", "value": 401.5, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "syyskuu 2026" },
      "method": "spending.total@1", "evidence_ref": "ev_g4i6k8m0o2q4",
      "label": "Ruokaostokset", "display": "401,50 €"
    },
    "n3": {
      "id": "n3", "value": 35.7, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "syyskuu ja elokuu 2026" },
      "method": "spending.change@1", "evidence_ref": "ev_g6i8k0m2o4q6",
      "label": "Muutos elokuusta", "display": "35,70 €"
    }
  },
  "cards": [
    {
      "card_id": "card_ans2b_01",
      "type": "metric",
      "title": "Ruokaostokset, syyskuu 2026",
      "subtitle": null,
      "evidence_ref": "ev_g4i6k8m0o2q4",
      "estimate": null,
      "status": null,
      "primary": {
        "id": "n1", "value": 401.5, "unit": "eur",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "syyskuu 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_g4i6k8m0o2q4",
        "label": "Ruokaostokset", "display": "401,50 €"
      },
      "secondary": [],
      "comparison": {
        "baseline": {
          "id": "n2", "value": 365.8, "unit": "eur",
          "period": { "start": "2026-08-01", "end": "2026-08-31", "label": "elokuu 2026" },
          "method": "spending.total@1", "evidence_ref": "ev_g5i7k9m1o3q5",
          "label": "Ruokaostokset, elokuu", "display": "365,80 €"
        },
        "change": {
          "id": "n3", "value": 35.7, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "syyskuu ja elokuu 2026" },
          "method": "spending.change@1", "evidence_ref": "ev_g6i8k0m2o4q6",
          "label": "Muutos elokuusta", "display": "35,70 €"
        },
        "change_pct": {
          "id": "n4", "value": 9.8, "unit": "percent",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "syyskuu ja elokuu 2026" },
          "method": "spending.change_pct@1", "evidence_ref": "ev_g1i3k5m7o9q1",
          "label": "Muutos elokuusta", "display": "9,8 %"
        },
        "tone": "neutral",
        "label": "elokuuhun verrattuna"
      },
      "components": [],
      "actions": [
        { "type": "open_evidence", "label": "Näytä ostokset", "evidence_ref": "ev_g4i6k8m0o2q4" },
        { "type": "ask", "label": "Missä ruoka on edullisinta?", "prompt": "Missä kaupassa ostaisin ruokani edullisimmin?" }
      ]
    }
  ],
  "follow_ups": [
    "Missä kaupassa ostaisin ruokani edullisimmin?",
    "Mitä jos käyttäisin ravintoloihin 20 % vähemmän?",
    "Mitkä laskut erääntyvät ennen palkkapäivää?"
  ],
  "lesson": null,
  "refusal": null,
  "clarify": null,
  "warnings": []
}
```

### 7.5 Refusals, clarifications and fallbacks

Refusal texts are fixed, reviewed templates, not free AI text. A refusal looks like any other answer with `outcome: "refused"` and no cards, so the app needs no special screen. It may style the bubble differently.

<!-- example: ask.json.request_refusal -->
```json
{
  "customer_id": "CUST00042",
  "conversation_id": "conv_4h8j2n6p",
  "message": "Should I put my savings into tech stocks?",
  "language": "auto"
}
```

<!-- example: ask.json.response_refusal -->
```json
{
  "answer_id": "ans_5c9e1g3j",
  "conversation_id": "conv_4h8j2n6p",
  "language": "en",
  "as_of": "2026-09-30",
  "outcome": "refused",
  "text": "I can't give investment advice, such as which shares or funds to buy. I can show you how much you could set aside each month, so you know what you have to work with. For investing, an S-Pankki advisor can help.",
  "text_rendered": "I can't give investment advice, such as which shares or funds to buy. I can show you how much you could set aside each month, so you know what you have to work with. For investing, an S-Pankki advisor can help.",
  "cited": [],
  "numbers": {},
  "cards": [],
  "follow_ups": [
    "How much could I set aside each month?",
    "What are my fixed bills?"
  ],
  "lesson": null,
  "refusal": { "kind": "investment_advice", "label": "Investment advice is outside what I can help with" },
  "clarify": null,
  "warnings": []
}
```

- **`clarify`:** the coach asks one short question back, with up to 3 options, and shows no cards. The user's reply, typed or tapped, goes into the same conversation.

<!-- example: ask.json.request_clarify -->
```json
{
  "customer_id": "CUST00042",
  "conversation_id": null,
  "message": "How much did I spend?",
  "language": "auto"
}
```

<!-- example: ask.json.response_clarify -->
```json
{
  "answer_id": "ans_6d0f2h4k",
  "conversation_id": "conv_8n2q4s6u",
  "language": "en",
  "as_of": "2026-09-30",
  "outcome": "clarify",
  "text": "Which period do you mean?",
  "text_rendered": "Which period do you mean?",
  "cited": [],
  "numbers": {},
  "cards": [],
  "follow_ups": [],
  "lesson": null,
  "refusal": null,
  "clarify": {
    "question": "Which period do you mean?",
    "options": ["This month", "Last month", "The last three months"]
  },
  "warnings": []
}
```

- **`fallback`:** if the AI model fails after the tools have run, the core still sends the cards and a template text built from them, for example "Here is what I found for September." `warnings` then contains `llm_unavailable`.

---

## 8. `POST /api/whatif`

A deterministic calculator for the what-if screen and its slider. No AI model is called. The same computation backs the `whatif` card in chat answers. It follows `metrics.md` section 4:
- The baseline is the average of the last 6 complete months, with one-off purchases left out.
- The saving is `cut_pct` of that baseline, given per month, per week and per year.

### 8.1 Request

| Field | Type | Meaning |
|---|---|---|
| `customer_id` | string | Persona. |
| `scenario` | object | `{selection: {kind, value}, cut_pct}`, see below. |
| `language` | `en` or `fi` | |

| `selection.kind` | `selection.value` | Example |
|---|---|---|
| `category` | A spending category (not an income, saving or transfer category) | `Restaurants` |
| `basket` | `regular_essentials`, `unexpected_necessities` or `everyday_spending` | `everyday_spending` |
| `mcc` | One or more MCC codes, comma-separated | `4121` (taxis) |
| `merchant` | A merchant id from a card. The AI model never sees merchant ids; the core maps them to the aliases the model uses. | `MRC-GRO-0035` |

`cut_pct` is a whole number from 1 to 100. Regular essentials are never cut: their part of a selection is left out of the baseline and shown as `regular_excluded`. The response's `status` is one of:
- `estimate`: the normal case, for example everyday spending.
- `estimate_with_caveat`: the selection includes unexpected necessities; the card says these are needed costs that can only sometimes be reduced.
- `not_offered`: nothing in the selection can be cut, for example `Groceries`, which is all regular essentials. All savings are 0.

If the selection has no spending in the window at all, the response is 422 `invalid_scenario`.

A store switch is not a what-if scenario. It is shown in the `stores` card with its own status (section 3).

<!-- example: whatif.request -->
```json
{
  "customer_id": "CUST00042",
  "scenario": { "selection": { "kind": "category", "value": "Restaurants" }, "cut_pct": 20 },
  "language": "en"
}
```

<!-- example: whatif.request_basket -->
```json
{
  "customer_id": "CUST00042",
  "scenario": { "selection": { "kind": "basket", "value": "everyday_spending" }, "cut_pct": 10 },
  "language": "en"
}
```

### 8.2 Response

<!-- example: whatif.response -->
```json
{
  "customer_id": "CUST00042",
  "as_of": "2026-09-30",
  "language": "en",
  "scenario": {
    "selection": { "kind": "category", "value": "Restaurants" },
    "cut_pct": {
      "value": 20, "unit": "percent",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "user_input@1", "evidence_ref": null,
      "label": "Cut you chose", "display": "20%"
    },
    "label": "Spend 20% less on restaurants"
  },
  "status": "estimate",
  "baseline_per_month": {
    "value": 268.4, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "what_if.baseline_month_eur@1", "evidence_ref": "ev_w1y3a5c7e9g1",
    "label": "Restaurants in a typical month", "display": "€268.40 a month"
  },
  "saving_per_month": {
    "value": 53.68, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "what_if.saving_month_eur@1", "evidence_ref": "ev_w3y5a7c9e1g3",
    "label": "You would save", "display": "€53.68 a month"
  },
  "saving_per_week": {
    "value": 12.35, "unit": "eur_per_week",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "what_if.saving_week_eur@1", "evidence_ref": "ev_w5y7a9c1e3g5",
    "label": "Per week", "display": "€12.35 a week"
  },
  "saving_per_year": {
    "value": 644.16, "unit": "eur_per_year",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "what_if.saving_year_eur@1", "evidence_ref": "ev_w4y6a8c0e2g4",
    "label": "Per year", "display": "€644.16 a year"
  },
  "one_off_excluded": {
    "value": 38.5, "unit": "eur",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "what_if.one_off_excluded_eur@1", "evidence_ref": "ev_w6y8a0c2e4g6",
    "label": "One-off purchases left out", "display": "€38.50"
  },
  "regular_excluded": {
    "value": 0.0, "unit": "eur",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "what_if.regular_excluded_eur@1", "evidence_ref": "ev_w7y9a1c3e5g7",
    "label": "Regular essentials left out", "display": "€0.00"
  },
  "assumptions": [
    "Average of your last 6 full months (one-off purchases left out), cut by 20%.",
    "The rest of your spending stays as it is."
  ],
  "caveats": ["This is an estimate, not a promise. Prices and habits change."],
  "estimate": { "label": "Estimate", "text": "Average of your last 6 full months (one-off purchases left out), cut by 20%." },
  "evidence_ref": "ev_w3y5a7c9e1g3"
}
```

---

## 9. `GET /api/evidence/{ref}`

Shows how a number was built: the method and either the transactions behind it or the numbers it was computed from. Evidence is for the app and the user only. It is never sent to the AI model.

**Request:** `GET /api/evidence/ev_r7t9v1x3z5b7?customer_id=CUST00042&lang=en&limit=50&cursor=<next_cursor>`

- `customer_id` must be the customer the evidence belongs to; otherwise the response is 403 `evidence_forbidden`.
- `limit` is 1 to 200 (default 50). `cursor` comes from the previous page.

`kind` decides which fields are filled:

| `kind` | Filled fields | Used for |
|---|---|---|
| `transactions` | `rows`, `row_count`, `reconciles`, `next_cursor` | Sums and counts over the customer's own transactions. |
| `composite` | `parts`: `{role, number: Number}`[] | Numbers computed from other numbers: changes, safe to spend, savings. Each part has its own `evidence_ref`. |
| `peer_aggregate` | `parts` (median, quartiles, group size) | Peer benchmarks. Shows group statistics only, never other customers' rows. |
| `store_index` | `parts` | Store price levels. |

Values the user typed in (`method` = `user_input@1`) have `evidence_ref: null`, so they have no evidence to open.

Transaction rows are source records, not coach numbers. Their `amount` is a **decimal string with the bank sign** (`"-24.50"` means €24.50 out), a common banking-API convention that avoids rounding errors. This is one of the two exemptions from the Number rule (section 1). `reconciles: true` confirms that the rows add up to `number`. For transfers that are not card purchases, `merchant` and `mcc` are `null`.

<!-- example: evidence.response -->
```json
{
  "evidence_ref": "ev_r7t9v1x3z5b7",
  "kind": "transactions",
  "language": "en",
  "title": "Restaurants, September 2026",
  "number": {
    "value": 312.8, "unit": "eur",
    "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
    "method": "spending.total@1", "evidence_ref": "ev_r7t9v1x3z5b7",
    "label": "Restaurants", "display": "€312.80"
  },
  "method": {
    "id": "spending.total@1",
    "name": "Total spending",
    "summary": "Money spent in the chosen categories during the period. Defined in the design document, section 6.2.",
    "doc": "docs/design/agent-core.md#62-data-tools"
  },
  "query": {
    "categories": ["Restaurants"],
    "baskets": [],
    "mcc_groups": [],
    "merchant_id": null,
    "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" }
  },
  "rows": [
    {
      "tx_id": "tx_2918344",
      "date": "2026-09-27",
      "time": "19:42",
      "category": "Restaurants",
      "merchant": { "id": "MRC-RES-0112", "label": "Restaurant A" },
      "mcc": "5812",
      "amount": "-24.50",
      "currency": "EUR"
    },
    {
      "tx_id": "tx_2918101",
      "date": "2026-09-25",
      "time": "12:05",
      "category": "Restaurants",
      "merchant": { "id": "MRC-RES-0047", "label": "Restaurant B" },
      "mcc": "5814",
      "amount": "-11.90",
      "currency": "EUR"
    }
  ],
  "row_count": {
    "value": 14, "unit": "count",
    "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
    "method": "evidence.row_count@1", "evidence_ref": "ev_r6t8v0x2z4b6",
    "label": "Transactions", "display": "14"
  },
  "reconciles": true,
  "parts": [],
  "next_cursor": "cur_2",
  "privacy_note": "Only you can see these transactions. They are never sent to the AI model."
}
```

<!-- example: evidence.response_composite -->
```json
{
  "evidence_ref": "ev_m3o5q7s9u1w3",
  "kind": "composite",
  "language": "en",
  "title": "Change from August to September",
  "number": {
    "value": 367.4, "unit": "eur",
    "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
    "method": "spending.change@1", "evidence_ref": "ev_m3o5q7s9u1w3",
    "label": "Change vs August", "display": "€367.40"
  },
  "method": {
    "id": "spending.change@1",
    "name": "Change between two periods",
    "summary": "The difference between spending in two periods. Defined in the design document, section 6.2.",
    "doc": "docs/design/agent-core.md#62-data-tools"
  },
  "query": null,
  "rows": [],
  "row_count": null,
  "reconciles": null,
  "parts": [
    {
      "role": "current",
      "number": {
        "value": 2315.6, "unit": "eur",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_k3m5p7r9t1v3",
        "label": "September spending", "display": "€2,315.60"
      }
    },
    {
      "role": "baseline",
      "number": {
        "value": 1948.2, "unit": "eur",
        "period": { "start": "2026-08-01", "end": "2026-08-31", "label": "August 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_a2c4e6g8i0k2",
        "label": "August spending", "display": "€1,948.20"
      }
    }
  ],
  "next_cursor": null,
  "privacy_note": "Only you can see this. Transactions are never sent to the AI model."
}
```

<!-- example: evidence.error -->
```json
{
  "error": {
    "code": "evidence_forbidden",
    "message": "This evidence belongs to another customer.",
    "retryable": false
  }
}
```

---

## 10. Changelog

| Version | Change |
|---|---|
| 0.1.0 | First draft: five endpoints, Number object, cards, streaming events (issue #5). |
| 0.1.1 | Review fixes:<br>- `/api/ask` validation errors (400, 404, 429) arrive as HTTP errors before the stream; the stream's `error` event uses the `{"error": …}` envelope.<br>- New `done.clarify` and a `warnings` code list.<br>- New `card.whatif` example; `estimate` and `evidence_ref` sit on the card, not in `result`.<br>- Breakdown key `other` documented.<br>- Conversations are bound to one customer.<br>- Evidence kind `input` removed.<br>- `ai_disclosure` uses the agreed default text.<br><br>Aligned with `metrics.md` (#6):<br>- Age bands and profile keys, traits and features as enums.<br>- Peer `level` replaces `widened`; peers need at least 20 others.<br>- Safe to spend covers the 7 days after today, with components and two limits.<br>- Bills carry the metrics `status`, with Utilities as one `spread` bill.<br>- What-if takes `{selection, cut_pct}` and returns a `status`, savings per month, week and year, and the excluded one-offs and regular essentials; `horizon`, `projected_per_month` and the cancel and switch scenarios are removed.<br>- `stores` carries confidence intervals and a `switch.status`, with no saving unless the status is `estimate`.<br>- Baskets show monthly averages over the window.<br>- Method ids are `<metric>.<output column>@<version>`, using the metrics output names. |
| 0.1.2 | Example values follow the safe-to-spend formula (#32).<br><br>New field:<br>- `metric.status` (`ok`, `below_usual`, `nothing_free` or `null`); the hero example carries `"status": "ok"`.<br><br>New method id:<br>- `safe_to_spend.bill_due_eur@1` for each bill's `due_until_payday` (pending as a SQL output column, issue #44); the bills total keeps `safe_to_spend.bills_due_eur@1`.<br><br>Changed example values in `overview.response`:<br>- essentials reserve 147.00 → 134.76;<br>- irregular reserve 61.50 → 167.46;<br>- free until payday 489.46 → 395.74;<br>- balance limit 228.41 → 184.68;<br>- budget limit 292.24 → 248.50;<br>- safe to spend 228.41 → 184.68;<br>- regular essentials 1,180.20 → 1,180.21 a month;<br>- total spending 2,211.00 → 2,211.01 a month.<br><br>`ask.json.response_fi` gains `"status": null` on its metric card. |
