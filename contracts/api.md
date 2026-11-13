# Core API contract

**Version:** 0.1.0 (draft) · **Issue:** #5 · **Design:** [docs/design/agent-core.md](../docs/design/agent-core.md)

**Status:** draft. A contract change needs an approving review from the app owner before merge.

This file is the interface between `core/` (the coach service) and `app/` (the mobile web app). The app can be built against the examples below before the core exists. Every example is tagged `<!-- example: <name> -->`, so a mock server can serve them by name.

All values in the examples are **illustrative**: they show shapes and consistent arithmetic, not results computed from the dataset. Metric definitions and method ids are owned by `docs/design/metrics.md` (issue #6). The method ids used here are placeholders until that document lands.

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
| Numbers | **Every number in a response is a [Number object](#21-number).** There are two exceptions. Raw transaction amounts in evidence rows are decimal strings (section 9). The `scenario` of an `open_whatif` action is a request payload that the app sends back to `/api/whatif` unchanged (section 8.1), so it may hold a plain number such as `change_pct`. |
| Merchants | Merchants are anonymised in the dataset. The core gives each merchant a label without digits that is stable for that customer, for example "Grocery store A" or "Restaurant B". The same label appears in cards, evidence and answer texts. |
| Ids | Opaque strings with a prefix: `CUST…` (customer, as in the dataset), `MRC-…` (merchant, as in the dataset), `ans_`, `conv_`, `card_`, `bill_`, `ev_` (evidence), `tx_` (transaction), `ins_` (insight). Ids `n1`, `n2`, … name numbers inside one answer. Do not parse ids. |
| Enum keys and labels | Every enum value the user sees (basket, category, profile, cadence, …) arrives as a stable `key` plus a separate localised `label`. Renaming a label never changes the key. |
| Baskets | `regular_essentials` ("Regular essentials"), `unexpected_necessities` ("Unexpected necessities"), `everyday_spending` ("Everyday spending"). These keys are shared with `docs/design/metrics.md`. |
| Categories | The 15 dataset categories, used as keys exactly as written: `Groceries`, `Restaurants`, `Transportation`, `Utilities`, `Entertainment`, `Health`, `Home & Tech`, `Housing`, `Lifestyle`, `Travel`, `Salary`, `Other Income`, `Invest Withdraw`, `Invest Deposit`, `Salary Sweep`. |
| Unknown fields | The app ignores fields it does not know. The core may add fields in a minor version, and removing or renaming a field is a major version change. |
| CORS | The core allows the app's dev and production origins. |
| Internal endpoints | `GET /api/audit/{answer_id}` returns the audit record of one answer (design doc, section 9). It is for the team and the eval run, not for the app, and is not part of this contract. |

---

## 2. Shared objects

### 2.1 Number

Every number the coach shows is one of these objects. A number can always be traced back to its source through `evidence_ref`.

| Field | Type | Meaning |
|---|---|---|
| `value` | number | The value. Money is in euros, rounded to cents. For `percent`, `12.5` means 12.5 %. |
| `unit` | enum | `eur`, `eur_per_day`, `eur_per_week`, `eur_per_month`, `eur_per_year`, `percent`, `percentile`, `count`, `days` |
| `period` | [Period](#22-period) | The time span the number describes. |
| `method` | string | The metric definition that produced it, `<metric_id>@<version>`, defined in `docs/design/metrics.md`. |
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
  "method": "spending_total@1",
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
| `estimate` | object or null | `{label, text}`. Set when the card shows an estimate rather than a fact: safe to spend, what-if and store savings. The app must show `label` (for example "Estimate") and make `text` (the assumption in plain words) reachable. |
| `actions` | Action[] | Buttons, at most 2. See below. |

Card-specific fields:

| `type` | Fields | Example |
|---|---|---|
| `metric` | `primary` Number; `secondary` Number[]; `comparison` Comparison or null; `components` `{key, label, operation: "add" or "subtract", amount: Number}`[] (empty when not relevant) | `overview.response` (hero), `ask.json.response_fi` |
| `breakdown` | `display_hint` (`list`, `stacked_bar` or `time_series`); `total` Number; `comparison` Comparison or null; `items` `{key, label, amount: Number, share: Number or null, change: Number or null, flags: ("one_off" or "habit")[]}`[] | `overview.response`, `ask.sse.card` |
| `bills` | `total` Number; `items` `{bill_id, label, category, cadence (weekly, monthly, quarterly, yearly or irregular), cadence_label, typical_amount: Number, last_paid, next_expected (date or null), confidence (high, medium or low), evidence_ref}`[] | `overview.response` |
| `peer` | `you`, `peer_median`, `peer_p25`, `peer_p75`, `percentile` (all Number); `peer_group` `{key, label, size: Number, widened: bool}`; `note` | `card.peer` |
| `stores` | `items` `{merchant: {id, label}, is_s_group (bool or null), price_index: Number, your_spend: Number, visits: Number}`[]; `estimated_saving` Number; `saving_range` `{low: Number, high: Number}`; `caveats` string[] | `card.stores` |
| `profile` | `profile` `{key, label, description}`; `traits` `{key, label, value: Number, note}`[] | `card.profile` |
| `whatif` | `result`: the body of a `POST /api/whatif` response without `customer_id`, `as_of` and `language`. `estimate` is always set. | `whatif.response` |

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
  "subtitle": "September 2026",
  "evidence_ref": "ev_q1s3u5w7y9a1",
  "estimate": null,
  "you": {
    "value": 312.8, "unit": "eur",
    "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
    "method": "spending_total@1", "evidence_ref": "ev_r7t9v1x3z5b7",
    "label": "You", "display": "€312.80"
  },
  "peer_median": {
    "value": 205.0, "unit": "eur",
    "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
    "method": "peer_median@1", "evidence_ref": "ev_q1s3u5w7y9a1",
    "label": "Typical for your group", "display": "€205.00"
  },
  "peer_p25": {
    "value": 140.0, "unit": "eur",
    "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
    "method": "peer_quantile@1", "evidence_ref": "ev_q2s4u6w8y0a2",
    "label": "Lower quarter", "display": "€140.00"
  },
  "peer_p75": {
    "value": 290.0, "unit": "eur",
    "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
    "method": "peer_quantile@1", "evidence_ref": "ev_q3s5u7w9y1a3",
    "label": "Upper quarter", "display": "€290.00"
  },
  "percentile": {
    "value": 81, "unit": "percentile",
    "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
    "method": "peer_percentile@1", "evidence_ref": "ev_q4s6u8w0y2a4",
    "label": "Your position", "display": "81st percentile"
  },
  "peer_group": {
    "key": "age_band_postal_area",
    "label": "Age 30-39, postal areas 005xx",
    "size": {
      "value": 214, "unit": "count",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
      "method": "peer_group_size@1", "evidence_ref": "ev_q5s7u9w1y3a5",
      "label": "People in the group", "display": "214"
    },
    "widened": false
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
  "subtitle": "Price level compared with the area average",
  "evidence_ref": "ev_p5r7t9v1x3z5",
  "estimate": {
    "label": "Estimate",
    "text": "Assumes you buy the same things at the other store, at the price level similar customers paid there."
  },
  "items": [
    {
      "merchant": { "id": "MRC-GRO-0035", "label": "Grocery store A" },
      "is_s_group": null,
      "price_index": {
        "value": 3.1, "unit": "percent",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "store_price_index@1", "evidence_ref": "ev_p5r7t9v1x3z5",
        "label": "Price level vs average", "display": "3.1%"
      },
      "your_spend": {
        "value": 301.1, "unit": "eur",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
        "method": "spending_total@1", "evidence_ref": "ev_g7i9k1m3o5q7",
        "label": "You spent here", "display": "€301.10"
      },
      "visits": {
        "value": 11, "unit": "count",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
        "method": "visit_count@1", "evidence_ref": "ev_g9i1k3m5o7q9",
        "label": "Visits", "display": "11"
      }
    },
    {
      "merchant": { "id": "MRC-GRO-0012", "label": "Grocery store B" },
      "is_s_group": null,
      "price_index": {
        "value": -2.4, "unit": "percent",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "store_price_index@1", "evidence_ref": "ev_p7r9t1v3x5z7",
        "label": "Price level vs average", "display": "-2.4%"
      },
      "your_spend": {
        "value": 100.4, "unit": "eur",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
        "method": "spending_total@1", "evidence_ref": "ev_g8i0k2m4o6q8",
        "label": "You spent here", "display": "€100.40"
      },
      "visits": {
        "value": 3, "unit": "count",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
        "method": "visit_count@1", "evidence_ref": "ev_g0i2k4m6o8q0",
        "label": "Visits", "display": "3"
      }
    }
  ],
  "estimated_saving": {
    "value": 16.1, "unit": "eur_per_month",
    "period": { "start": "2026-10-01", "end": "2026-10-31", "label": "A typical month" },
    "method": "store_switch_saving@1", "evidence_ref": "ev_p6r8t0v2x4z6",
    "label": "Possible saving", "display": "€16.10 a month"
  },
  "saving_range": {
    "low": {
      "value": 6.0, "unit": "eur_per_month",
      "period": { "start": "2026-10-01", "end": "2026-10-31", "label": "A typical month" },
      "method": "store_switch_saving_low@1", "evidence_ref": "ev_p8r0t2v4x6z8",
      "label": "Low estimate", "display": "€6.00 a month"
    },
    "high": {
      "value": 24.0, "unit": "eur_per_month",
      "period": { "start": "2026-10-01", "end": "2026-10-31", "label": "A typical month" },
      "method": "store_switch_saving_high@1", "evidence_ref": "ev_p9r1t3v5x7z9",
      "label": "High estimate", "display": "€24.00 a month"
    }
  },
  "caveats": [
    "Price levels are estimated from what similar customers paid, not from shelf prices.",
    "Which stores belong to S-Group is a demo assumption."
  ],
  "actions": [
    {
      "type": "open_whatif",
      "label": "Try switching",
      "scenario": { "type": "switch_grocery_store", "from_merchant_id": "MRC-GRO-0035", "to_merchant_id": "MRC-GRO-0012" }
    }
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
    "key": "social_spender",
    "label": "Social spender",
    "description": "Your fixed bills are steady, and you spend more freely on eating out."
  },
  "traits": [
    {
      "key": "restaurants_share",
      "label": "Eating out, share of spending",
      "value": {
        "value": 13.5, "unit": "percent",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
        "method": "category_share@1", "evidence_ref": "ev_x2z4b6d8f0h2",
        "label": "Eating out share", "display": "13.5%"
      },
      "note": "Higher than most people your age."
    },
    {
      "key": "regular_essentials_share",
      "label": "Regular essentials, share of spending",
      "value": {
        "value": 56.7, "unit": "percent",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
        "method": "basket_share@1", "evidence_ref": "ev_bs1a3c5e7g9i",
        "label": "Regular essentials share", "display": "56.7%"
      },
      "note": "Most of your money goes to costs you can plan for."
    }
  ],
  "actions": []
}
```

---

## 4. Errors

Every error response has the same envelope. The app shows `message` (already localised) and offers a retry when `retryable` is true.

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

Lists the demo customers the app can switch between. These are curated customers from the synthetic dataset. Display names are invented and labelled as demo personas.

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
      "age_band": "30-39",
      "postal_area": { "code": "00530", "label": "Helsinki 00530" },
      "profile": { "key": "social_spender", "label": "Social spender" },
      "tagline": "Steady salary, rents in Helsinki, eats out often.",
      "default_language": "en"
    },
    {
      "customer_id": "CUST00017",
      "display_name": "Mikko",
      "age_band": "50-59",
      "postal_area": { "code": "02100", "label": "Espoo 02100" },
      "profile": { "key": "steady_planner", "label": "Steady planner" },
      "tagline": "Predictable bills, one regular grocery store.",
      "default_language": "fi"
    },
    {
      "customer_id": "CUST00088",
      "display_name": "Leena",
      "age_band": "18-29",
      "postal_area": { "code": "00100", "label": "Helsinki 00100" },
      "profile": { "key": "variable_income", "label": "Variable income" },
      "tagline": "Part-time income and some expensive months.",
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
- `hero`: a `metric` card, safe to spend this week. Its component keys and `estimate.text` are placeholders until `metrics.md` (#6) defines the formula. The shape stays.
- `cards`: Card[] (spending baskets, bills before payday, and more later).
- `insights`: Insight[].
- `suggested_questions`: string[], sent to `/api/ask` when tapped. These are the partner's four questions.

An Insight is `{insight_id, kind, title, text, text_rendered, numbers, estimate, action}`:
- `kind` is one of `habit_trend`, `one_off`, `bill_change`, `store_saving`, `peer_gap`, `low_safe_to_spend`.
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
  "ai_disclosure": "I'm an AI assistant. My numbers come from your own transactions, and you can tap any number to see where it comes from.",
  "hero": {
    "card_id": "card_sts_01",
    "type": "metric",
    "title": "Safe to spend this week",
    "subtitle": "Today until Sunday",
    "evidence_ref": "ev_s2t4w6y8a0c2",
    "estimate": {
      "label": "Estimate",
      "text": "Your balance minus the bills you usually pay before payday and a small safety buffer."
    },
    "primary": {
      "value": 186.4, "unit": "eur",
      "period": { "start": "2026-09-30", "end": "2026-10-04", "label": "Rest of this week" },
      "method": "safe_to_spend@1", "evidence_ref": "ev_s2t4w6y8a0c2",
      "label": "Safe to spend", "display": "€186.40"
    },
    "secondary": [
      {
        "value": 37.28, "unit": "eur_per_day",
        "period": { "start": "2026-09-30", "end": "2026-10-04", "label": "Rest of this week" },
        "method": "safe_to_spend_daily@1", "evidence_ref": "ev_s3t5w7y9a1c3",
        "label": "Per day", "display": "€37.28 a day"
      }
    ],
    "comparison": null,
    "components": [
      {
        "key": "available_balance",
        "label": "Money on your account",
        "operation": "add",
        "amount": {
          "value": 1240.15, "unit": "eur",
          "period": { "start": "2026-09-30", "end": "2026-09-30", "label": "30 Sep 2026" },
          "method": "balance_now@1", "evidence_ref": "ev_b4l6n8p0r2t4",
          "label": "Balance", "display": "€1,240.15"
        }
      },
      {
        "key": "bills_before_payday",
        "label": "Bills due before payday",
        "operation": "subtract",
        "amount": {
          "value": 905.0, "unit": "eur",
          "period": { "start": "2026-09-30", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "upcoming_bills_total@1", "evidence_ref": "ev_u6b8d0f2h4j6",
          "label": "Bills before payday", "display": "€905.00"
        }
      },
      {
        "key": "safety_buffer",
        "label": "Safety buffer",
        "operation": "subtract",
        "amount": {
          "value": 148.75, "unit": "eur",
          "period": { "start": "2026-09-30", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safety_buffer@1", "evidence_ref": "ev_f8h0j2l4n6p8",
          "label": "Buffer", "display": "€148.75"
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
      "title": "Where your money went in September",
      "subtitle": "Spending in three baskets",
      "evidence_ref": "ev_k3m5p7r9t1v3",
      "estimate": null,
      "display_hint": "stacked_bar",
      "total": {
        "value": 2315.6, "unit": "eur",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
        "method": "spending_total@1", "evidence_ref": "ev_k3m5p7r9t1v3",
        "label": "Total spending", "display": "€2,315.60"
      },
      "comparison": null,
      "items": [
        {
          "key": "regular_essentials",
          "label": "Regular essentials",
          "amount": {
            "value": 1312.4, "unit": "eur",
            "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
            "method": "basket_amount@1", "evidence_ref": "ev_br1a3c5e7g9i",
            "label": "Regular essentials", "display": "€1,312.40"
          },
          "share": {
            "value": 56.7, "unit": "percent",
            "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
            "method": "basket_share@1", "evidence_ref": "ev_bs1a3c5e7g9i",
            "label": "Share of spending", "display": "56.7%"
          },
          "change": null,
          "flags": []
        },
        {
          "key": "unexpected_necessities",
          "label": "Unexpected necessities",
          "amount": {
            "value": 418.9, "unit": "eur",
            "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
            "method": "basket_amount@1", "evidence_ref": "ev_bi2b4d6f8h0j",
            "label": "Unexpected necessities", "display": "€418.90"
          },
          "share": {
            "value": 18.1, "unit": "percent",
            "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
            "method": "basket_share@1", "evidence_ref": "ev_bt2b4d6f8h0j",
            "label": "Share of spending", "display": "18.1%"
          },
          "change": null,
          "flags": []
        },
        {
          "key": "everyday_spending",
          "label": "Everyday spending",
          "amount": {
            "value": 584.3, "unit": "eur",
            "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
            "method": "basket_amount@1", "evidence_ref": "ev_bl3c5e7g9i1k",
            "label": "Everyday spending", "display": "€584.30"
          },
          "share": {
            "value": 25.2, "unit": "percent",
            "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September 2026" },
            "method": "basket_share@1", "evidence_ref": "ev_bu3c5e7g9i1k",
            "label": "Share of spending", "display": "25.2%"
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
      "subtitle": "Expected 1 to 15 October",
      "evidence_ref": "ev_u6b8d0f2h4j6",
      "estimate": null,
      "total": {
        "value": 905.0, "unit": "eur",
        "period": { "start": "2026-09-30", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "upcoming_bills_total@1", "evidence_ref": "ev_u6b8d0f2h4j6",
        "label": "Bills before payday", "display": "€905.00"
      },
      "items": [
        {
          "bill_id": "bill_hou_01",
          "label": "Housing",
          "category": "Housing",
          "cadence": "monthly",
          "cadence_label": "Monthly, around the 1st",
          "typical_amount": {
            "value": 780.0, "unit": "eur",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "recurring_amount@1", "evidence_ref": "ev_h1o3u5s7e9a1",
            "label": "Usual amount", "display": "€780.00"
          },
          "last_paid": "2026-09-01",
          "next_expected": "2026-10-01",
          "confidence": "high",
          "evidence_ref": "ev_h1o3u5s7e9a1"
        },
        {
          "bill_id": "bill_uti_01",
          "label": "Utilities, early month",
          "category": "Utilities",
          "cadence": "monthly",
          "cadence_label": "Monthly, around the 6th",
          "typical_amount": {
            "value": 62.3, "unit": "eur",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "recurring_amount@1", "evidence_ref": "ev_h2o4u6s8e0a2",
            "label": "Usual amount", "display": "€62.30"
          },
          "last_paid": "2026-09-07",
          "next_expected": "2026-10-06",
          "confidence": "high",
          "evidence_ref": "ev_h2o4u6s8e0a2"
        },
        {
          "bill_id": "bill_uti_02",
          "label": "Utilities, around the 9th",
          "category": "Utilities",
          "cadence": "monthly",
          "cadence_label": "Monthly, around the 9th",
          "typical_amount": {
            "value": 24.9, "unit": "eur",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "recurring_amount@1", "evidence_ref": "ev_h3o5u7s9e1a3",
            "label": "Usual amount", "display": "€24.90"
          },
          "last_paid": "2026-09-09",
          "next_expected": "2026-10-09",
          "confidence": "medium",
          "evidence_ref": "ev_h3o5u7s9e1a3"
        },
        {
          "bill_id": "bill_uti_03",
          "label": "Utilities, mid-month",
          "category": "Utilities",
          "cadence": "monthly",
          "cadence_label": "Monthly, around the 13th",
          "typical_amount": {
            "value": 37.8, "unit": "eur",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "recurring_amount@1", "evidence_ref": "ev_h4o6u8s0e2a4",
            "label": "Usual amount", "display": "€37.80"
          },
          "last_paid": "2026-09-14",
          "next_expected": "2026-10-13",
          "confidence": "medium",
          "evidence_ref": "ev_h4o6u8s0e2a4"
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
          "method": "spending_total@1", "evidence_ref": "ev_r7t9v1x3z5b7",
          "label": "Restaurants", "display": "€312.80"
        },
        "n2": {
          "id": "n2", "value": 91.7, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
          "method": "spending_change@1", "evidence_ref": "ev_r8t0v2x4z6b8",
          "label": "Change vs August", "display": "€91.70"
        }
      },
      "estimate": null,
      "action": { "type": "ask", "label": "How can I spend less on eating out?", "prompt": "How can I spend less on restaurants?" }
    },
    {
      "insight_id": "ins_store_01",
      "kind": "store_saving",
      "title": "Groceries could cost less",
      "text": "Prices at your usual grocery store are {{n1}} above the area average. Switching could save about {{n2}}.",
      "text_rendered": "Prices at your usual grocery store are 3.1% above the area average. Switching could save about €16.10 a month.",
      "numbers": {
        "n1": {
          "id": "n1", "value": 3.1, "unit": "percent",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "store_price_index@1", "evidence_ref": "ev_p5r7t9v1x3z5",
          "label": "Price level vs average", "display": "3.1%"
        },
        "n2": {
          "id": "n2", "value": 16.1, "unit": "eur_per_month",
          "period": { "start": "2026-10-01", "end": "2026-10-31", "label": "A typical month" },
          "method": "store_switch_saving@1", "evidence_ref": "ev_p6r8t0v2x4z6",
          "label": "Possible saving", "display": "€16.10 a month"
        }
      },
      "estimate": {
        "label": "Estimate",
        "text": "Assumes you buy the same things at the other store, at the price level similar customers paid there."
      },
      "action": {
        "type": "open_whatif",
        "label": "Try switching",
        "scenario": { "type": "switch_grocery_store", "from_merchant_id": "MRC-GRO-0035", "to_merchant_id": "MRC-GRO-0012" }
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
| `conversation_id` | string or null | `null` starts a new conversation. Send the id from `meta` to ask a follow-up. The server keeps the history (last 6 turns, 30 minutes). The app does not resend it. |
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
| `done` | Last, once, on success | `answer_id`, `outcome`, `text` (full, with tokens), `text_rendered`, `cited` (number ids used), `follow_ups` (string[]), `lesson` (`{key, title, text}` or null), `refusal` (`{kind, label}` or null), `warnings` (string[]) |
| `error` | Last, once, on failure | `code`, `message`, `retryable` (section 4) |

`outcome` is one of:
- `answered`: a normal answer.
- `clarify`: the coach asks a question back.
- `refused`: out of scope; see `refusal.kind`.
- `fallback`: the AI model was unavailable, so the text is a template built from the tool results.

`refusal.kind` is one of `investment_advice`, `out_of_scope`, `other_person_data` or `unsafe`.

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
      "method": "spending_total@1", "evidence_ref": "ev_k3m5p7r9t1v3",
      "label": "Total spending", "display": "€2,315.60"
    },
    "comparison": {
      "baseline": {
        "id": "n2", "value": 1948.2, "unit": "eur",
        "period": { "start": "2026-08-01", "end": "2026-08-31", "label": "August 2026" },
        "method": "spending_total@1", "evidence_ref": "ev_a2c4e6g8i0k2",
        "label": "August spending", "display": "€1,948.20"
      },
      "change": {
        "id": "n3", "value": 367.4, "unit": "eur",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
        "method": "spending_change@1", "evidence_ref": "ev_m3o5q7s9u1w3",
        "label": "Change vs August", "display": "€367.40"
      },
      "change_pct": {
        "id": "n4", "value": 18.9, "unit": "percent",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
        "method": "spending_change_pct@1", "evidence_ref": "ev_m4o6q8s0u2w4",
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
          "method": "spending_total@1", "evidence_ref": "ev_t2v4x6z8b0d2",
          "label": "Travel", "display": "€240.00"
        },
        "share": null,
        "change": {
          "id": "n6", "value": 240.0, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
          "method": "spending_change@1", "evidence_ref": "ev_t3v5x7z9b1d3",
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
          "method": "spending_total@1", "evidence_ref": "ev_r7t9v1x3z5b7",
          "label": "Restaurants", "display": "€312.80"
        },
        "share": null,
        "change": {
          "id": "n8", "value": 91.7, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
          "method": "spending_change@1", "evidence_ref": "ev_r8t0v2x4z6b8",
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
          "method": "spending_total@1", "evidence_ref": "ev_o1q3s5u7w9y1",
          "label": "Everything else", "display": "€1,762.80"
        },
        "share": null,
        "change": {
          "id": "n10", "value": 35.7, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
          "method": "spending_change@1", "evidence_ref": "ev_o2q4s6u8w0y2",
          "label": "Everything else, change vs August", "display": "€35.70"
        },
        "flags": []
      }
    ],
    "actions": [
      { "type": "open_evidence", "label": "See September transactions", "evidence_ref": "ev_k3m5p7r9t1v3" },
      { "type": "ask", "label": "Spend 20% less on restaurants?", "prompt": "What if I spend 20% less on restaurants?" }
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
      "method": "spending_total@1", "evidence_ref": "ev_k3m5p7r9t1v3",
      "label": "Total spending", "display": "€2,315.60"
    },
    "n3": {
      "id": "n3", "value": 367.4, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
      "method": "spending_change@1", "evidence_ref": "ev_m3o5q7s9u1w3",
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
      "method": "spending_total@1", "evidence_ref": "ev_t2v4x6z8b0d2",
      "label": "Travel", "display": "€240.00"
    },
    "n8": {
      "id": "n8", "value": 91.7, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "September vs August 2026" },
      "method": "spending_change@1", "evidence_ref": "ev_r8t0v2x4z6b8",
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
data: {"card":{"card_id":"card_ans7f_01","type":"breakdown","title":"September compared with August","subtitle":"Biggest changes by category","evidence_ref":"ev_k3m5p7r9t1v3","estimate":null,"display_hint":"list","total":{"id":"n1","value":2315.6,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending_total@1","evidence_ref":"ev_k3m5p7r9t1v3","label":"Total spending","display":"€2,315.60"},"comparison":{"baseline":{"id":"n2","value":1948.2,"unit":"eur","period":{"start":"2026-08-01","end":"2026-08-31","label":"August 2026"},"method":"spending_total@1","evidence_ref":"ev_a2c4e6g8i0k2","label":"August spending","display":"€1,948.20"},"change":{"id":"n3","value":367.4,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending_change@1","evidence_ref":"ev_m3o5q7s9u1w3","label":"Change vs August","display":"€367.40"},"change_pct":{"id":"n4","value":18.9,"unit":"percent","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending_change_pct@1","evidence_ref":"ev_m4o6q8s0u2w4","label":"Change vs August","display":"18.9%"},"tone":"worse","label":"vs August 2026"},"items":[{"key":"Travel","label":"Travel","amount":{"id":"n5","value":240.0,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending_total@1","evidence_ref":"ev_t2v4x6z8b0d2","label":"Travel","display":"€240.00"},"share":null,"change":{"id":"n6","value":240.0,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending_change@1","evidence_ref":"ev_t3v5x7z9b1d3","label":"Travel, change vs August","display":"€240.00"},"flags":["one_off"]},{"key":"Restaurants","label":"Restaurants","amount":{"id":"n7","value":312.8,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending_total@1","evidence_ref":"ev_r7t9v1x3z5b7","label":"Restaurants","display":"€312.80"},"share":null,"change":{"id":"n8","value":91.7,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending_change@1","evidence_ref":"ev_r8t0v2x4z6b8","label":"Restaurants, change vs August","display":"€91.70"},"flags":["habit"]},{"key":"other","label":"Everything else","amount":{"id":"n9","value":1762.8,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending_total@1","evidence_ref":"ev_o1q3s5u7w9y1","label":"Everything else","display":"€1,762.80"},"share":null,"change":{"id":"n10","value":35.7,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending_change@1","evidence_ref":"ev_o2q4s6u8w0y2","label":"Everything else, change vs August","display":"€35.70"},"flags":[]}],"actions":[{"type":"open_evidence","label":"See September transactions","evidence_ref":"ev_k3m5p7r9t1v3"},{"type":"ask","label":"Spend 20% less on restaurants?","prompt":"What if I spend 20% less on restaurants?"}]}}

event: numbers
data: {"numbers":{"n1":{"id":"n1","value":2315.6,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending_total@1","evidence_ref":"ev_k3m5p7r9t1v3","label":"Total spending","display":"€2,315.60"},"n3":{"id":"n3","value":367.4,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending_change@1","evidence_ref":"ev_m3o5q7s9u1w3","label":"Change vs August","display":"€367.40"}}}

event: delta
data: {"text":"September cost {{n1}}, which is {{n3}} more than August. "}

event: numbers
data: {"numbers":{"n5":{"id":"n5","value":240.0,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},"method":"spending_total@1","evidence_ref":"ev_t2v4x6z8b0d2","label":"Travel","display":"€240.00"},"n8":{"id":"n8","value":91.7,"unit":"eur","period":{"start":"2026-09-01","end":"2026-09-30","label":"September vs August 2026"},"method":"spending_change@1","evidence_ref":"ev_r8t0v2x4z6b8","label":"Restaurants, change vs August","display":"€91.70"}}}

event: delta
data: {"text":"Most of the increase is Travel at {{n5}}, which looks like a one-off, and Restaurants, up {{n8}}. "}

event: delta
data: {"text":"A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust."}

event: done
data: {"answer_id":"ans_7f3k9q2m","outcome":"answered","text":"September cost {{n1}}, which is {{n3}} more than August. Most of the increase is Travel at {{n5}}, which looks like a one-off, and Restaurants, up {{n8}}. A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust.","text_rendered":"September cost €2,315.60, which is €367.40 more than August. Most of the increase is Travel at €240.00, which looks like a one-off, and Restaurants, up €91.70. A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust.","cited":["n1","n3","n5","n8"],"follow_ups":["What if I spend 20% less on restaurants?","How could I save more?","What can I safely spend this week?"],"lesson":{"key":"one_off_vs_habit","title":"One-offs and habits","text":"A one-off cost, like a trip, shows up once. A habit, like eating out, repeats every month, so a small change there adds up over a year."},"refusal":null,"warnings":[]}
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
data: {"code":"data_unavailable","message":"Your data can't be loaded right now. Please try again in a minute.","retryable":true}
```

<!-- example: ask.sse.error -->
```json
{ "code": "data_unavailable", "message": "Your data can't be loaded right now. Please try again in a minute.", "retryable": true }
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
      "method": "spending_total@1", "evidence_ref": "ev_g4i6k8m0o2q4",
      "label": "Ruokaostokset", "display": "401,50 €"
    },
    "n3": {
      "id": "n3", "value": 35.7, "unit": "eur",
      "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "syyskuu ja elokuu 2026" },
      "method": "spending_change@1", "evidence_ref": "ev_g6i8k0m2o4q6",
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
      "primary": {
        "id": "n1", "value": 401.5, "unit": "eur",
        "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "syyskuu 2026" },
        "method": "spending_total@1", "evidence_ref": "ev_g4i6k8m0o2q4",
        "label": "Ruokaostokset", "display": "401,50 €"
      },
      "secondary": [],
      "comparison": {
        "baseline": {
          "id": "n2", "value": 365.8, "unit": "eur",
          "period": { "start": "2026-08-01", "end": "2026-08-31", "label": "elokuu 2026" },
          "method": "spending_total@1", "evidence_ref": "ev_g5i7k9m1o3q5",
          "label": "Ruokaostokset, elokuu", "display": "365,80 €"
        },
        "change": {
          "id": "n3", "value": 35.7, "unit": "eur",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "syyskuu ja elokuu 2026" },
          "method": "spending_change@1", "evidence_ref": "ev_g6i8k0m2o4q6",
          "label": "Muutos elokuusta", "display": "35,70 €"
        },
        "change_pct": {
          "id": "n4", "value": 9.8, "unit": "percent",
          "period": { "start": "2026-09-01", "end": "2026-09-30", "label": "syyskuu ja elokuu 2026" },
          "method": "spending_change_pct@1", "evidence_ref": "ev_g1i3k5m7o9q1",
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
    "Mitä jos käyttäisin ruokaan 10 % vähemmän?",
    "Mitkä laskut erääntyvät ennen palkkapäivää?"
  ],
  "lesson": null,
  "refusal": null,
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
  "warnings": []
}
```

- **`clarify`:** the coach asks one short question back, for example "Do you mean this month or last month?". There are no cards. The user's reply goes into the same conversation.
- **`fallback`:** if the AI model fails after the tools have run, the core still sends the cards and a template text built from them, for example "Here is what I found for September." `warnings` then contains `llm_unavailable`.

---

## 8. `POST /api/whatif`

A deterministic scenario calculator for the what-if screen and its sliders. No AI model is called. The same computation backs the `whatif` card in chat answers.

### 8.1 Request

| Field | Type | Meaning |
|---|---|---|
| `customer_id` | string | Persona. |
| `scenario` | object | One of the scenario types below. |
| `horizon` | enum | `next_month`, `next_3_months` or `next_12_months` (default). |
| `language` | `en` or `fi` | |

| `scenario.type` | Fields | Meaning |
|---|---|---|
| `category_change` | `category` (one of the 15 categories), `change_pct` (from -100 to 100) | Spend this much more or less in one category. |
| `basket_change` | `basket` (`regular_essentials`, `unexpected_necessities` or `everyday_spending`), `change_pct` | The same for a whole basket. |
| `cancel_recurring` | `bill_id` (from a `bills` card) | Stop one recurring payment. |
| `switch_grocery_store` | `from_merchant_id`, `to_merchant_id` | Buy groceries at another store. |

<!-- example: whatif.request -->
```json
{
  "customer_id": "CUST00042",
  "scenario": { "type": "category_change", "category": "Restaurants", "change_pct": -20 },
  "horizon": "next_12_months",
  "language": "en"
}
```

<!-- example: whatif.request_cancel -->
```json
{
  "customer_id": "CUST00042",
  "scenario": { "type": "cancel_recurring", "bill_id": "bill_uti_02" },
  "horizon": "next_3_months",
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
    "type": "category_change",
    "category": "Restaurants",
    "change_pct": {
      "value": -20, "unit": "percent",
      "period": { "start": "2026-10-01", "end": "2027-09-30", "label": "Next 12 months" },
      "method": "user_input@1", "evidence_ref": null,
      "label": "Change you chose", "display": "-20%"
    },
    "label": "Spend 20% less on restaurants"
  },
  "horizon": { "start": "2026-10-01", "end": "2027-09-30", "label": "Next 12 months" },
  "baseline_per_month": {
    "value": 268.4, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Typical month, Apr-Sep 2026" },
    "method": "whatif_baseline@1", "evidence_ref": "ev_w1y3a5c7e9g1",
    "label": "Restaurants now", "display": "€268.40 a month"
  },
  "projected_per_month": {
    "value": 214.72, "unit": "eur_per_month",
    "period": { "start": "2026-10-01", "end": "2027-09-30", "label": "Next 12 months" },
    "method": "whatif_projection@1", "evidence_ref": "ev_w2y4a6c8e0g2",
    "label": "Restaurants with the change", "display": "€214.72 a month"
  },
  "saving_per_month": {
    "value": 53.68, "unit": "eur_per_month",
    "period": { "start": "2026-10-01", "end": "2027-09-30", "label": "Next 12 months" },
    "method": "whatif_saving@1", "evidence_ref": "ev_w3y5a7c9e1g3",
    "label": "You would save", "display": "€53.68 a month"
  },
  "saving_over_horizon": {
    "value": 644.16, "unit": "eur",
    "period": { "start": "2026-10-01", "end": "2027-09-30", "label": "Next 12 months" },
    "method": "whatif_saving_total@1", "evidence_ref": "ev_w4y6a8c0e2g4",
    "label": "Saved in 12 months", "display": "€644.16"
  },
  "assumptions": [
    "Your typical restaurant month is estimated from your recent history.",
    "The rest of your spending stays as it is."
  ],
  "caveats": [
    "This is an estimate, not a promise. Prices and habits change."
  ],
  "estimate": {
    "label": "Estimate",
    "text": "Based on your typical restaurant month. The rest of your spending stays as it is."
  },
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
| `input` | Nothing extra | Values the user typed in. |

Transaction rows are source records, not coach numbers. Their `amount` is a **decimal string with the bank sign** (`"-24.50"` means €24.50 out), a common banking-API convention that avoids rounding errors. This is the only place where a numeric value is not a Number object. `reconciles: true` confirms that the rows add up to `number`. For transfers that are not card purchases, `merchant` and `mcc` are `null`.

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
    "method": "spending_total@1", "evidence_ref": "ev_r7t9v1x3z5b7",
    "label": "Restaurants", "display": "€312.80"
  },
  "method": {
    "id": "spending_total@1",
    "name": "Total spending",
    "summary": "Money spent in the chosen categories during the period. The full definition is in the metrics document.",
    "doc": "docs/design/metrics.md#spending_total"
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
    "method": "row_count@1", "evidence_ref": "ev_r6t8v0x2z4b6",
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
    "method": "spending_change@1", "evidence_ref": "ev_m3o5q7s9u1w3",
    "label": "Change vs August", "display": "€367.40"
  },
  "method": {
    "id": "spending_change@1",
    "name": "Change between two periods",
    "summary": "The difference between spending in two periods. The full definition is in the metrics document.",
    "doc": "docs/design/metrics.md#spending_change"
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
        "method": "spending_total@1", "evidence_ref": "ev_k3m5p7r9t1v3",
        "label": "September spending", "display": "€2,315.60"
      }
    },
    {
      "role": "baseline",
      "number": {
        "value": 1948.2, "unit": "eur",
        "period": { "start": "2026-08-01", "end": "2026-08-31", "label": "August 2026" },
        "method": "spending_total@1", "evidence_ref": "ev_a2c4e6g8i0k2",
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
