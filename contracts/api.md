# Core API contract

**Version:** 0.3.4 (draft) · **Issues:** #5, #32, #33, #44, #53, #134, #242, #243, #267, #382, #420, #421 · **Design:** [docs/design/agent-core.md](../docs/design/agent-core.md)

**Status:** draft 0.3.4. The app owner raises changes through a new issue, and each change bumps the version in the changelog.

This file is the interface between `core/` (the coach service) and `app/` (the mobile web app). The app can be built against the examples below before the core exists. Every example is tagged `<!-- example: <name> -->`, so a mock server can serve them by name.

All values in the examples are **illustrative**: they show shapes and consistent arithmetic, not results computed from the dataset. The exceptions are computed from the dataset (`metrics.md` sections 1.1 and 3.1):
- `overview.response_pending`, `card.review`, `card.safe_to_save` and the label examples in section 10, for CUST00860 (persona Sanna);
- `card.safe_to_save_aleksi`, for CUST00849 (persona Aleksi);
- `card.safe_to_save_zero`, for CUST00002, and `card.safe_to_save_everyday`, for CUST00019 (customers of the metrics sample).

Metric definitions are owned by `docs/design/metrics.md` (issue #6). Method ids, enums and windows here follow it (section 2.1, `method`).

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
10. [`POST /api/baskets/label`](#10-post-apibasketslabel)
11. [`POST /api/bill/explain`](#11-post-apibillexplain)
12. [Changelog](#12-changelog)

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | `/api`. Request and response bodies are JSON in UTF-8, except the `/api/ask` stream (section 7). |
| Customer | Demo mode has no login: the app picks a persona from `/api/personas` and sends its `customer_id`. In production the customer comes from the bank session and the field is ignored. The core never lets the AI model choose the customer. **Only the persona customers are served:** any other `customer_id`, also a real customer of the dataset, gets 404 `customer_not_found`, exactly like an id that does not exist (section 4). |
| "Today" | Fixed by the server setting `DEMO_TODAY` (default `2026-09-30`). Every response carries it as `as_of`. Nothing after `as_of` is treated as history. Later dates are predictions such as an expected bill. |
| Language | `en` or `fi`. GET endpoints take `?lang=en` or `?lang=fi` (default `en`). POST bodies take `language` (default `en`). `/api/ask` also accepts `auto`, its default: the language is detected from the message, typed with or without ä and ö, and is English when unsure. Every response says which `language` was used. All labels, `display` strings and texts arrive already localised. The app does not translate. Error messages follow the same language: `?lang` for a GET, the body's `language` for a POST, and for `/api/ask` with `auto` the detected language. A POST body that cannot be read or does not validate (400 `invalid_request`) has no language: it is answered in the language of the `lang` query parameter, else in English, and on `/api/ask` always in English. A `/api/ask` message over 500 characters with `auto` is answered in English too, because its language is not detected. |
| Dates | `YYYY-MM-DD`. Periods are inclusive at both ends. |
| Timestamps | ISO 8601 with offset, for example `2026-11-14T10:32:05+02:00`. They are wall-clock times of events such as `labelled_at`, not dataset dates. |
| Money sign | Spending, bills and income are **positive** amounts. A `change` is signed: positive means more than the baseline. A `components[]` entry carries a positive `amount` and an `operation` (`add` or `subtract`). Raw transaction rows in evidence keep the bank sign: negative means money out. |
| Numbers | **Every number in a response is a [Number object](#21-number).** There are three exceptions. Raw transaction amounts in evidence rows are decimal strings (section 9). The `scenario` of an `open_whatif` action is a request payload that the app sends back to `/api/whatif` unchanged (section 8.1), so it may hold a plain number such as `cut_pct`. A bill reading (section 11.4) is a proposal for the user to confirm, so its fields, the amount included, are strings. |
| Merchants | Merchants are anonymised in the dataset. The core gives each merchant a label without digits that is stable for that customer, for example "Grocery store A" or "Restaurant B". The same label appears in cards, evidence and answer texts. |
| Ids | Opaque strings with a prefix: `CUST…` (customer, as in the dataset), `MRC-…` (merchant, as in the dataset), `ans_`, `conv_`, `card_`, `bill_`, `ev_` (evidence), `tx_` (transaction), `ins_` (insight). Ids `n1`, `n2`, … name numbers inside one answer. Do not parse ids. |
| Enum keys and labels | Every enum value the user sees (basket, category, profile, cadence, …) arrives as a stable `key` plus a separate localised `label`. Renaming a label never changes the key. |
| Baskets | `regular_essentials` ("Regular essentials"), `unexpected_necessities` ("Unexpected necessities"), `everyday_spending` ("Everyday spending"). These keys are shared with `docs/design/metrics.md`. A purchase with a pending review is in a fourth state, `unclassified` ("Waiting for your answer", Finnish "Odottaa vastaustasi"), shown only while that review is pending (section 6). |
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
| `method` | string | The definition that produced the number, `<metric>.<output column>@<version>`. `<metric>` is a metric of `docs/design/metrics.md` named after its SQL file in `core/metrics/` (`recurring`, `baskets`, `safe_to_spend`, `what_if`, `spender_profile`, `peer_benchmark`, `store_price_index`), and the output column is the one listed there, for example `safe_to_spend.safe_to_spend_7d_eur@1`. The balance forecast until payday (`metrics.md` section 3.3, #257) uses `balance_forecast.daily_pace_eur@1` (usual spending a day, `eur_per_day`), `balance_forecast.bills_to_date_eur@1` (the bills due by that day, `eur`) and `balance_forecast.balance_eur@1` (the projected balance on that day, `eur`, a composite). Plain sums and counts that `metrics.md` does not define use `spending.*` and `evidence.*`, which are defined in the design document (section 6.2). Values the user typed in use `user_input@1`. Values read from a bill's virtual barcode use `bill_barcode@1`, and the numbers the bill explanation computes use `bill.*` (section 11). |
| `evidence_ref` | string or null | Pass it to `GET /api/evidence/{ref}` to see how the number was built. One ref backs exactly one number (one `method` and `value`), and the same number shown in several places carries the same ref. It is `null` in three cases only: values the user typed in (`method` = `user_input@1`), values read from a bill's virtual barcode (`bill_barcode@1`, section 11), and the parts of a `peer_aggregate` evidence view (section 9), which are group statistics with no further drill-down by design. |
| `label` | string | Short localised name, for example "Restaurants". |
| `display` | string | Localised formatted value, for example `€312.80` or `312,80 €`. A plus sign is never added. Negative values show a minus. A display with a direction word (`more`, `less`) shows the magnitude without a minus. Every display is written by one formatter on the server from the number's `value`, `unit` and `method`, so the app never formats a number itself:<br>- money and rates: `€1,180.21 a month` / `1 180,21 € / kk`;<br>- percentages with one decimal, `18.9%` / `18,9 %`, except a whole percentage the user typed (`user_input@1`): `20%` / `20 %`;<br>- percentiles as ordinals: `72nd percentile` / `72. persentiili`;<br>- the gap to the peer median (`peer_benchmark.vs_median_pct@1`) with a direction word: `32.3% more`, `31.0% less` / `32,3 % enemmän`, `31,0 % vähemmän`; exactly zero is `0.0%`;<br>- counts: whole counts grouped like money, `4,120` / `4 120`; a fractional count with one decimal, `15.2` / `15,2`; everyday purchases a month (`spender_profile.everyday_tx_month@1`) as `14.2 a month` / `14,2 / kk`;<br>- `days` and `months` with their unit: `1 day`, `12 days` / `1 pv`, `12 pv`;<br>- a value that rounds to zero never shows a minus: `€0.00`, not `-€0.00`. |
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
| `type` | enum | `metric`, `breakdown`, `bills`, `peer`, `stores`, `profile`, `whatif`, `review`, `safe_to_save` |
| `title` | string | Localised. |
| `subtitle` | string or null | Localised. |
| `evidence_ref` | string or null | Evidence for the card as a whole. |
| `estimate` | object or null | `{label, text}`. Set when the card shows an estimate rather than a fact: the safe-to-spend `metric` card, and the `bills` (pro rata amounts), `peer`, `whatif` and `stores` cards. The app must show `label` (for example "Estimate") and make `text` (the assumption in plain words) reachable. |
| `actions` | Action[] | Buttons, at most 2. See below. |

Card-specific fields:

| `type` | Fields | Example |
|---|---|---|
| `metric` | `status` (string or null); `primary` Number; `secondary` Number[]; `comparison` Comparison or null; `components` `{key, label, operation: "add" or "subtract", amount: Number}`[] (empty when not relevant). On the safe-to-spend card, `secondary` lists free until payday, the balance limit, the budget limit and the savings goal (`safe_to_spend.savings_goal_eur@1`, a monthly amount set aside first; `metrics.md` section 3, #391). The budget limit is computed after the goal, so safe to spend and the goal add up. `status` is set only on the safe-to-spend card and is one of `ok`, `below_usual` or `nothing_free` (`metrics.md` section 3). Use it for tone and colour; it is `null` on every other `metric` card. For safe to spend (`metrics.md` section 3): the components `balance`, `bills_due`, `essentials_reserve`, `irregular_reserve` and `cushion` add up to the first secondary number, "Free until payday". Spread over the days to payday, it gives the balance limit (second secondary number). The primary number is the smaller of the balance limit and the budget limit (third secondary number). Each value is rounded to cents separately, so in real responses the components may differ from "Free until payday" by 0.01. The examples add up exactly. | `overview.response` (hero), `ask.json.response_fi` |
| `breakdown` | `display_hint` (`list`, `stacked_bar` or `time_series`); `total` Number; `comparison` Comparison or null; `items` `{key, label, amount: Number, share: Number or null, change: Number or null, flags: ("one_off" or "habit")[]}`[]. An item `key` is a category, basket, MCC group or month, or `other` for everything outside the top items; in a dated breakdown (`display_hint` `time_series`, the balance forecast of #257) the keys are ISO dates (`YYYY-MM-DD`), one item per date in date order. | `overview.response`, `ask.sse.card` |
| `bills` | `total` Number; `items` `{bill_id, label, category, cadence, status, status_label, typical_month: Number, last_paid, next_expected (date or null), due_until_payday: Number, evidence_ref}`[]. `cadence` is `monthly`, the only cadence in this data. `status` is one of `spread` (several payments a month, counted pro rata), `done_this_month`, `upcoming`, `late` or `skipped_this_month` (`metrics.md` section 2). Methods:
- `total` uses `safe_to_spend.bills_due_eur@1`, the per-customer total.
- Each `due_until_payday` uses `safe_to_spend.bill_due_eur@1`: one bill's term of that total. For a once-a-month bill that is its typical amount for each due date before payday, and for a `spread` bill its pro rata share: both are computed in the `bill_items` step of `core/metrics/03_safe_to_spend.sql`, which the `bills` step sums.
- `safe_to_spend.bill_due_eur` is the column of the per-bill output `core/metrics/03_safe_to_spend_bills.sql` (`metrics.md` section 3.2, one row per bill due before payday).
- The items' `due_until_payday` add up to `total`. Each item is rounded on its own and the total once, from the same unrounded terms, so in real responses the sum can differ from `total` by up to 0.01 per item (each item's rounding moves it by at most 0.005; for example 928.51 against 928.50 with two items). The examples add up exactly. | `overview.response` |
| `peer` | `you`, `peer_median`, `peer_p25`, `peer_p75` (monthly averages), `percentile`, `vs_median` (all Number); `peer_group` `{level, label, size: Number, comparable: bool}`; `note`. `level` is `age_band+area3`, `age_band+city`, `age_band` or `all`: the most specific group with at least 20 other customers (`metrics.md` section 6). Without such a group, or for a customer whose salary is swept elsewhere, there is no peer card. Health is never benchmarked. | `card.peer` |
| `stores` | `items` `{merchant: {id, label}, is_s_group (bool or null), price_index: Number, price_index_ci95: {low: Number, high: Number} or null, differs_from_average: bool, visits: Number}`[]; `switch` `{status, status_label, home: {id, label}, alternative: {id, label} or null, home_spend_month: Number, ticket_gap: Number or null, estimated_saving: Number or null}`; `caveats` string[]. `switch.status` is `estimate`, `within_noise`, `already_lowest`, `not_measurable` or `no_alternative`. Only `estimate` carries a gap and a saving (`metrics.md` section 7). | `card.stores` |
| `profile` | `profile` `{key, label, description}`; `traits` `{key, label, note}`[]; `features` `{key, decides_label: bool, value: Number}`[]. `profile.key` is `not_enough_income_data`, `stretched`, `big_ticket`, `everyday_heavy`, `saver` or `steady`. `not_enough_income_data` means the account shows too little income for a verdict. `traits[].key` is any of `salary_moved_elsewhere`, `went_below_zero`, `regular_investor`, `weekend_spender` or `frequent_small_purchases`. `features[].key` is a profile feature from `metrics.md` section 5, using the exact names from there, for example `keep_rate`, `one_off_share`, `everyday_share_pct`, `everyday_weekend_pct` or `everyday_tx_month`. | `card.profile` |
| `whatif` | `result`: `{scenario, status, baseline_per_month, saving_per_month, saving_per_week, saving_per_year, one_off_excluded, regular_excluded, assumptions, caveats}`. That is the `POST /api/whatif` body without `customer_id`, `as_of` and `language`, and without `estimate` and `evidence_ref`, which sit on the card itself. `estimate` is always set. | `card.whatif` |
| `review` | The coach asks about one spending spike (design doc, section 7.8). Fields:<br>- `tx_ref`: an opaque token for this question. It is not the transaction id; send it to section 10.<br>- `date`, `category`, `merchant` `{alias, label}` or null (no merchant id; the label has no digits), `amount` (Number).<br>- `current_basket` `{key, label}`: where the purchase sits now. While the review is pending this is always `unclassified` ("Waiting for your answer"): the purchase is in no basket total and not in the reserve.<br>- `question` `{en, fi}`: the question in both languages, with the purchase's amount (its display), category and date filled in, for example "€1,080.42 at Home & Tech on 28 September 2026 — needed, or your choice?".<br>- `options`: exactly two, `{basket, label: {en, fi}, effect: {en, fi}}`, for `unexpected_necessities` ("Needed" / "Välttämätön") and `everyday_spending` ("My choice" / "Oma valinta"). The three basket keys stay the only answer options; `unclassified` is never one.<br>- `why`: why the coach asks, in the request language.<br><br>Tapping an option sends `POST /api/baskets/label` with its `basket`. Question and option texts are fixed templates, never written by the AI model. | `card.review`, `overview.response_pending` |
| `safe_to_save` | Fields (`metrics.md` section 3.1; `estimate` is always set):<br>- `monthly` (Number, the headline): what a typical month leaves, never below 0.<br>- `monthly_components` `{key, label, operation, amount}`[]: no amount is ever negative. The app renders them as listed:<br>&nbsp;&nbsp;- when free month ≥ 0: `free_month` add and `everyday_month` subtract; `monthly` is their difference, or 0 when it is negative;<br>&nbsp;&nbsp;- when free month < 0: only `essentials_shortfall` (the shortfall as a positive amount, subtract), and `monthly` is 0.<br>- `stock` (Number): money in the account beyond what is needed until payday.<br>- `stock_explanation`: one sentence, never a call to action. Nothing on the card says where to put money (R7).<br>- `stock_components`: `free_until_payday` add, `everyday_until_payday` subtract. `stock` is their sum, or 0 when negative. When free until payday itself is negative, `stock` is 0 and `stock_components` is empty, so no amount is ever negative.<br>- `subtitle` (#391): with a savings goal, the goal next to safe to spend ("You could set aside about €360.00 a month on top of spending about €138.79 a week."), or, when `monthly` is below the goal, the goal against `monthly` ("Your goal is €360.00 a month; at your usual pace about €184.61 a month would be left."); with no goal "What a typical month leaves".<br>- `reason`: `null` unless `monthly` is 0. Then it is `{kind, category, amount: Number, text}`:<br>&nbsp;&nbsp;- The rule is on the sign of free month.<br>&nbsp;&nbsp;- `essentials_exceed_income` (free month < 0): bills, the saving the customer set up, usual essentials and the reserve already exceed income, so even no everyday spending would leave nothing. `category` is `null`, and `amount` is the monthly shortfall.<br>&nbsp;&nbsp;- `largest_everyday_category` (free month ≥ 0, but everyday spending uses it up). `category` `{key, label}` is the `everyday_spending` category with the largest share of the everyday month, and `amount` is that category's figure on the same basis as `everyday_month`: one-offs left out, window total ÷ window days × 30.4375. A sensitive category is never named (R9); `everyday_spending` holds none today.<br>&nbsp;&nbsp;- `text` carries no digits; the app shows `amount` next to it.<br><br>Method ids: `safe_to_spend.safe_to_save_monthly_eur`, `.everyday_month_eur`, `.safe_to_save_eur`, `.everyday_until_payday_eur`, `.essentials_shortfall_month_eur`, `.save_reason_month_eur`, `.free_month_eur` and `.free_until_payday_eur`, all output columns of `03_safe_to_spend.sql`. The reason's `kind` and `category` are its columns `save_reason` and `save_reason_category`.<br><br>`actions`: `open_evidence`, and when `monthly` is above 0 also `open_host_screen` with the target `monthly_saving` (#267). That action only leads to the host's own screen; it names no product, fund or amount, so R7 still holds. | `card.safe_to_save`, `card.safe_to_save_aleksi`, `card.safe_to_save_zero`, `card.safe_to_save_everyday`, `overview.response`, `overview.response_pending` |

Actions:

| `type` | Fields | App behaviour |
|---|---|---|
| `open_evidence` | `label`, `evidence_ref` | Open the evidence sheet. |
| `ask` | `label`, `prompt` | Send `prompt` to `/api/ask` in the same conversation. |
| `open_whatif` | `label`, `scenario` (same shape as the `scenario` of a `/api/whatif` request, section 8.1) | Open the what-if screen with this scenario. |
| `open_host_screen` | `label`, `target`: `monthly_saving`, `bonus_to_fund` or `contact_bank` | Send the host message `sentti.openHostScreen` with `{target}`; the host opens its own screen (below). |

**`open_host_screen`** (since 0.3.1, #267) leads from a card to a screen of the host app (S-mobiili). It is one step into the bank's own app: Sentti recommends nothing there and moves no money.
- `target` comes from a closed list, and no other value is ever sent:
  - `monthly_saving`: the host's monthly saving screen. Carried by the `safe_to_save` card when `monthly` is above 0; when `monthly` is 0 the card has no such action.
  - `bonus_to_fund`: the host's Bonus to fund screen. Carried by the S-Bonus estimate, a `metric` card titled "S-Bonus estimate" in answers to the S-Bonus question, only when the estimate is offered. When the Bonus would be 0 because spending is below the lowest level of the table, the card has no such action.
  - `contact_bank` (since 0.3.3, #420): the host's own way to contact S-Pankki, a human at the bank. Carried in `/api/ask` by every refusal, by the "I can't answer that one yet" answer and by the "nothing found" fallback (`done.actions`, section 7), and by a bill explanation with a failed check or an unknown payee together with another sign (`actions`, section 11). Sentti hands over and says nothing about what the bank will do.
- `label` names the destination only, for example "See monthly saving in S-mobiili" / "Katso kuukausisäästäminen S-mobiilissa" and "See Bonus to fund in S-mobiili" / "Katso Bonus rahastoon S-mobiilissa", and "Contact S-Pankki" / "Ota yhteyttä S-Pankkiin". It has no digits, no fund or product name, nothing about returns and no "you should".
- The action carries no amount, no evidence ref and no customer data. The app sends the host only `{target}`: the message `sentti.openHostScreen` in the app's `sentti.<name>` envelope (`docs/integration.md` section 3; the envelope of PR #175). The host shows its own screen with its own figures and terms. The service expects no answer and stores nothing.
- The host ignores a target it does not know. The app renders an action whose target it does not know as nothing. In the demo build, which has no host, the app opens a mock host sheet for the target instead (#268).
- Issues #267 and #268 wrote the message name as `sentti.open_host_screen`. It follows the camelCase names of the app's envelope, as `sentti.openTransaction` and `sentti.paymentDraft` (section 11.3) do, so it is `sentti.openHostScreen`. The action type in this API stays `open_host_screen`.

<!-- example: action.open_host_screen -->
```json
{
  "type": "open_host_screen",
  "label": "See monthly saving in S-mobiili",
  "target": "monthly_saving"
}
```

The host message it sends:

<!-- example: host.open_host_screen -->
```json
{
  "type": "sentti.openHostScreen",
  "v": 1,
  "payload": { "target": "monthly_saving" }
}
```

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

The `review` card for Sanna's Home & Tech purchase (values from the dataset):

<!-- example: card.review -->
```json
{
  "card_id": "card_review_01",
  "type": "review",
  "title": "One question about a large purchase",
  "subtitle": "Home & Tech, 28 September 2026",
  "evidence_ref": "ev_rv1x3z5b7d9f",
  "estimate": null,
  "tx_ref": "txr_k7m2q9w4z8c3v6b1",
  "date": "2026-09-28",
  "category": "Home & Tech",
  "merchant": { "alias": "store_a", "label": "Home and tech store A" },
  "amount": {
    "value": 1080.42, "unit": "eur",
    "period": { "start": "2026-09-28", "end": "2026-09-28", "label": "28 Sep 2026" },
    "method": "spending.total@1", "evidence_ref": "ev_rv1x3z5b7d9f",
    "label": "Home & Tech purchase", "display": "€1,080.42"
  },
  "current_basket": { "key": "unclassified", "label": "Waiting for your answer" },
  "question": {
    "en": "€1,080.42 at Home & Tech on 28 September 2026 — needed, or your choice?",
    "fi": "1 080,42 € Koti ja tekniikka, 28.9.2026 — välttämätön hankinta vai oma valinta?"
  },
  "options": [
    {
      "basket": "unexpected_necessities",
      "label": { "en": "Needed", "fi": "Välttämätön" },
      "effect": {
        "en": "It counts as an unexpected necessity. Sentti keeps a bigger reserve for surprises like this, so your safe to spend goes down.",
        "fi": "Se lasketaan välttämättömäksi yllätysmenoksi. Sentti varaa jatkossa enemmän rahaa tällaisiin yllätyksiin, joten turvallisesti käytettävissä oleva summa pienenee."
      }
    },
    {
      "basket": "everyday_spending",
      "label": { "en": "My choice", "fi": "Oma valinta" },
      "effect": {
        "en": "It counts as everyday spending. Your safe to spend stays the same; your everyday spending this month is higher than usual.",
        "fi": "Se lasketaan arkikulutukseksi. Turvallisesti käytettävissä oleva summa pysyy ennallaan, mutta arkikulutuksesi on tässä kuussa tavallista suurempi."
      }
    }
  ],
  "why": "Only you know what this purchase was. Your answer changes only how your own spending is grouped.",
  "actions": [
    { "type": "open_evidence", "label": "See the purchase", "evidence_ref": "ev_rv1x3z5b7d9f" }
  ]
}
```

The `safe_to_save` card of the overview for Sanna after she answered "needed" (values from the dataset). These are the same numbers as with no review at all. While her review is pending, the card shows 364.31 a month instead (`overview.response_pending`):

<!-- example: card.safe_to_save -->
```json
{
  "card_id": "card_save_01",
  "type": "safe_to_save",
  "title": "Safe to save",
  "subtitle": "Your goal is €360.00 a month; at your usual pace about €184.61 a month would be left.",
  "evidence_ref": "ev_sn3m5o7n9t1h",
  "estimate": {
    "label": "Estimate",
    "text": "A typical month of your last six: income minus bills, saving you set up, usual essentials, a reserve for unexpected costs and your usual everyday spending."
  },
  "monthly": {
    "value": 184.61, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sn3m5o7n9t1h",
    "label": "Typically left each month", "display": "€184.61 a month"
  },
  "monthly_components": [
    {
      "key": "free_month",
      "label": "Left after bills, essentials and the reserve",
      "operation": "add",
      "amount": {
        "value": 783.79, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.free_month_eur@1", "evidence_ref": "ev_sn5f7m9o1n3t",
        "label": "Free in a typical month", "display": "€783.79 a month"
      }
    },
    {
      "key": "everyday_month",
      "label": "Usual everyday spending",
      "operation": "subtract",
      "amount": {
        "value": 599.18, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.everyday_month_eur@1", "evidence_ref": "ev_sn6e8v0m2o4n",
        "label": "Everyday spending in a typical month", "display": "€599.18 a month"
      }
    }
  ],
  "stock": {
    "value": 12272.28, "unit": "eur",
    "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
    "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_sn2s4a6v8e0n",
    "label": "In your account beyond what you need until payday", "display": "€12,272.28"
  },
  "stock_explanation": "Money in your account beyond what you need until payday, after bills, reserves, a small cushion and your usual everyday spending.",
  "stock_components": [
    {
      "key": "free_until_payday",
      "label": "Free until payday",
      "operation": "add",
      "amount": {
        "value": 12567.56, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_sn1f3r5e7e9u",
        "label": "Free until payday", "display": "€12,567.56"
      }
    },
    {
      "key": "everyday_until_payday",
      "label": "Usual everyday spending until payday",
      "operation": "subtract",
      "amount": {
        "value": 295.28, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.everyday_until_payday_eur@1", "evidence_ref": "ev_sn4e6v8d0y2p",
        "label": "Everyday spending until payday", "display": "€295.28"
      }
    }
  ],
  "reason": null,
  "actions": [
    { "type": "open_evidence", "label": "How is this calculated?", "evidence_ref": "ev_sn3m5o7n9t1h" },
    { "type": "open_host_screen", "label": "See monthly saving in S-mobiili", "target": "monthly_saving" }
  ]
}
```

For Aleksi (CUST00849, values from the dataset), a tight but positive month: no reason line.

<!-- example: card.safe_to_save_aleksi -->
```json
{
  "card_id": "card_save_03",
  "type": "safe_to_save",
  "title": "Safe to save",
  "subtitle": "You could set aside about €190.00 a month on top of spending about €123.15 a week.",
  "evidence_ref": "ev_al1m3o5n7t9h",
  "estimate": {
    "label": "Estimate",
    "text": "A typical month of your last six: income minus bills, saving you set up, usual essentials, a reserve for unexpected costs and your usual everyday spending."
  },
  "monthly": {
    "value": 199.95, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_al1m3o5n7t9h",
    "label": "Typically left each month", "display": "€199.95 a month"
  },
  "monthly_components": [
    {
      "key": "free_month",
      "label": "Left after bills, essentials and the reserve",
      "operation": "add",
      "amount": {
        "value": 725.47, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.free_month_eur@1", "evidence_ref": "ev_al2f4m6o8n0t",
        "label": "Free in a typical month", "display": "€725.47 a month"
      }
    },
    {
      "key": "everyday_month",
      "label": "Usual everyday spending",
      "operation": "subtract",
      "amount": {
        "value": 525.52, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.everyday_month_eur@1", "evidence_ref": "ev_al3e5v7m9o1n",
        "label": "Everyday spending in a typical month", "display": "€525.52 a month"
      }
    }
  ],
  "stock": {
    "value": 560.64, "unit": "eur",
    "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
    "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_al4s6a8v0e2n",
    "label": "In your account beyond what you need until payday", "display": "€560.64"
  },
  "stock_explanation": "Money in your account beyond what you need until payday, after bills, reserves, a small cushion and your usual everyday spending.",
  "stock_components": [
    {
      "key": "free_until_payday",
      "label": "Free until payday",
      "operation": "add",
      "amount": {
        "value": 819.62, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_al5f7r9e1e3u",
        "label": "Free until payday", "display": "€819.62"
      }
    },
    {
      "key": "everyday_until_payday",
      "label": "Usual everyday spending until payday",
      "operation": "subtract",
      "amount": {
        "value": 258.98, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.everyday_until_payday_eur@1", "evidence_ref": "ev_al6e8v0d2y4p",
        "label": "Everyday spending until payday", "display": "€258.98"
      }
    }
  ],
  "reason": null,
  "actions": [
    { "type": "open_evidence", "label": "How is this calculated?", "evidence_ref": "ev_al1m3o5n7t9h" },
    { "type": "open_host_screen", "label": "See monthly saving in S-mobiili", "target": "monthly_saving" }
  ]
}
```

When a typical month leaves nothing, the headline is 0 and `reason` says why. First, CUST00002 of the metrics sample (dataset values): free month is already negative, so the reason is `essentials_exceed_income`, and the only component is the shortfall:

<!-- example: card.safe_to_save_zero -->
```json
{
  "card_id": "card_save_04",
  "type": "safe_to_save",
  "title": "Safe to save",
  "subtitle": "What a typical month leaves",
  "evidence_ref": "ev_zr1m3o5n7t9h",
  "estimate": {
    "label": "Estimate",
    "text": "A typical month of your last six: income minus bills, saving you set up, usual essentials, a reserve for unexpected costs and your usual everyday spending."
  },
  "monthly": {
    "value": 0.0, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_zr1m3o5n7t9h",
    "label": "Typically left each month", "display": "€0.00 a month"
  },
  "monthly_components": [
    {
      "key": "essentials_shortfall",
      "label": "Short before any everyday spending",
      "operation": "subtract",
      "amount": {
        "value": 1.59, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.essentials_shortfall_month_eur@1", "evidence_ref": "ev_zr2s4h6o8r0t",
        "label": "Bills, essentials and the reserve above income", "display": "€1.59 a month"
      }
    }
  ],
  "stock": {
    "value": 10.07, "unit": "eur",
    "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
    "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_zr4s6a8v0e2n",
    "label": "In your account beyond what you need until payday", "display": "€10.07"
  },
  "stock_explanation": "Money in your account beyond what you need until payday, after bills, reserves, a small cushion and your usual everyday spending.",
  "stock_components": [
    {
      "key": "free_until_payday",
      "label": "Free until payday",
      "operation": "add",
      "amount": {
        "value": 198.47, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_zr5f7r9e1e3u",
        "label": "Free until payday", "display": "€198.47"
      }
    },
    {
      "key": "everyday_until_payday",
      "label": "Usual everyday spending until payday",
      "operation": "subtract",
      "amount": {
        "value": 188.4, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.everyday_until_payday_eur@1", "evidence_ref": "ev_zr6e8v0d2y4p",
        "label": "Everyday spending until payday", "display": "€188.40"
      }
    }
  ],
  "reason": {
    "kind": "essentials_exceed_income",
    "category": null,
    "amount": {
      "value": 1.59, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "safe_to_spend.save_reason_month_eur@1", "evidence_ref": "ev_zr7s9h1o3r5t",
      "label": "Short each month", "display": "€1.59 a month"
    },
    "text": "Nothing is left in a typical month: your bills, the saving you set up, usual essentials and the reserve for unexpected costs already come to more than your income."
  },
  "actions": [
    { "type": "open_evidence", "label": "How is this calculated?", "evidence_ref": "ev_zr1m3o5n7t9h" }
  ]
}
```

Second, CUST00019 of the metrics sample (dataset values): free month is positive, but her usual everyday spending uses it up, so the reason names the largest everyday category:

<!-- example: card.safe_to_save_everyday -->
```json
{
  "card_id": "card_save_05",
  "type": "safe_to_save",
  "title": "Safe to save",
  "subtitle": "What a typical month leaves",
  "evidence_ref": "ev_ev1m3o5n7t9h",
  "estimate": {
    "label": "Estimate",
    "text": "A typical month of your last six: income minus bills, saving you set up, usual essentials, a reserve for unexpected costs and your usual everyday spending."
  },
  "monthly": {
    "value": 0.0, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
    "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_ev1m3o5n7t9h",
    "label": "Typically left each month", "display": "€0.00 a month"
  },
  "monthly_components": [
    {
      "key": "free_month",
      "label": "Left after bills, essentials and the reserve",
      "operation": "add",
      "amount": {
        "value": 398.89, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.free_month_eur@1", "evidence_ref": "ev_ev2f4m6o8n0t",
        "label": "Free in a typical month", "display": "€398.89 a month"
      }
    },
    {
      "key": "everyday_month",
      "label": "Usual everyday spending",
      "operation": "subtract",
      "amount": {
        "value": 585.33, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.everyday_month_eur@1", "evidence_ref": "ev_ev3e5v7m9o1n",
        "label": "Everyday spending in a typical month", "display": "€585.33 a month"
      }
    }
  ],
  "stock": {
    "value": 285.07, "unit": "eur",
    "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
    "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_ev4s6a8v0e2n",
    "label": "In your account beyond what you need until payday", "display": "€285.07"
  },
  "stock_explanation": "Money in your account beyond what you need until payday, after bills, reserves, a small cushion and your usual everyday spending.",
  "stock_components": [
    {
      "key": "free_until_payday",
      "label": "Free until payday",
      "operation": "add",
      "amount": {
        "value": 573.53, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_ev5f7r9e1e3u",
        "label": "Free until payday", "display": "€573.53"
      }
    },
    {
      "key": "everyday_until_payday",
      "label": "Usual everyday spending until payday",
      "operation": "subtract",
      "amount": {
        "value": 288.46, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.everyday_until_payday_eur@1", "evidence_ref": "ev_ev6e8v0d2y4p",
        "label": "Everyday spending until payday", "display": "€288.46"
      }
    }
  ],
  "reason": {
    "kind": "largest_everyday_category",
    "category": { "key": "Restaurants", "label": "Restaurants" },
    "amount": {
      "value": 186.93, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "safe_to_spend.save_reason_month_eur@1", "evidence_ref": "ev_ev7r9e1s3t5a",
      "label": "Restaurants in a typical month", "display": "€186.93 a month"
    },
    "text": "Nothing is left in a typical month. Your largest everyday spending category is Restaurants."
  },
  "actions": [
    { "type": "open_evidence", "label": "How is this calculated?", "evidence_ref": "ev_ev1m3o5n7t9h" }
  ]
}
```

---

## 4. Errors

Every error response has the same envelope, and the `error` event inside the `/api/ask` stream uses it too. The app shows `message` (already localised: `?lang` for a GET, the body's `language` for a POST, the detected language for `/api/ask` with `auto`; for a POST body that cannot be read or does not validate, see section 1) and offers a retry when `retryable` is true. A 422 `invalid_bill` adds one field, `reason` (section 11.1).

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid_request` | Malformed body or a bad parameter. A what-if selection the core refuses is a 422 `invalid_scenario` instead (section 8.1). |
| 404 | `customer_not_found` | Unknown `customer_id`, or any customer that is not a persona (section 1): both get the same answer. |
| 404 | `not_found` | Unknown route: the path names no endpoint of this contract. |
| 405 | `invalid_request` | A known path with a method it does not take. The `Allow` header lists the methods it takes. |
| 404 | `evidence_not_found` | Unknown or expired `ref`. |
| 403 | `evidence_forbidden` | The evidence belongs to a different customer. |
| 422 | `invalid_scenario` | The what-if scenario cannot be computed or is refused: a selection with no spending in the window, or a selection the core refuses (section 8.1). Every reason gets the same body. |
| 422 | `invalid_bill` | The bill explanation cannot use the request: both or neither of `barcode` and `fields`, `payee` beside `fields`, or a barcode that cannot be used. The body carries `reason`, and `message` is the sentence for that reason (section 11.1). |
| 404 | `tx_ref_not_found` | Unknown `tx_ref`, the ref of an expired review, or one that belongs to another customer. All three get the same answer, so a caller cannot tell whether another customer's ref exists (section 10, R4). |
| 422 | `basket_not_allowed` | The basket is not one of the review's two options (section 10). |
| 429 | `rate_limited` | Too many requests. Retry after the `Retry-After` header. |
| 503 | `data_unavailable` | The database cannot be reached or is too slow. |
| 503 | `llm_unavailable` | Only when there is no fallback answer at all. Normally `/api/ask` answers with a template instead (section 7.5). |
| 503 | `model_unavailable` | A bill reading cannot use the model; the app offers typing the fields (section 11.4, not implemented yet). |
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

Lists the demo customers the app can switch between. These are curated customers from the synthetic dataset, and the only customers the service answers for (section 1). Display names are invented and labelled as demo personas. `age_band` uses the age bands from section 1, and `profile.key` uses the profile keys of the `profile` card (section 3).

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

The home screen. It is fully deterministic: no AI model is called, and its numbers come from precomputed tables only, so it is fast and **safe to call on every app open**.
- **One idempotent side effect:** when the customer has no pending review and a spike qualifies, the first serve **creates the pending review** and its `tx_ref` (design doc, section 7.8). Later calls return the same pending review; it is never created twice. A prefetch that receives a new review therefore counts as asking it.
- **After a label:** the per-customer refresh finishes before `POST /api/baskets/label` returns, so the overview fetched afterwards already shows the new numbers.
- **Per-viewer state (#144):**
  - The overview sets one first-party, functional cookie when the request has none: `sentti_viewer`, a random value with no personal data, `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=7200`.
  - Review answers are stored per viewer, so one viewer's answer never changes another viewer's numbers. A client without the cookie sees the shared pending state.
  - The app needs no change: the cookie is same-origin.

**Request:** `GET /api/overview/CUST00042?lang=en`

**Response fields:**
- `customer_id`, `as_of`, `language`, `greeting`.
- `ai_disclosure`: show it on the first chat screen.
- `hero`: a `metric` card, safe to spend in the next 7 days (`metrics.md` section 3; how its components work is in section 3 of this contract). Its `status` field carries the metrics status (`ok`, `below_usual` or `nothing_free`). The subtitle carries the period's dates in the project's period format, for example "1–7 Oct 2026" (Finnish "1.–7.10.2026"), not the status. **`hero` is `null`** when safe to spend cannot be computed for a known reason (the bills before payday do not match the metric, or the customer has no transactions up to `as_of`). The rest of the overview is unaffected, and the app hides the card.
- `safe_to_save`: a card of type `safe_to_save` (section 3, `metrics.md` section 3.1). The headline is `monthly`, what a typical month leaves. The second line is `stock` with its one-sentence `stock_explanation`, money in the account beyond what is needed until payday; the app shows it with no call to action. It is **not** added to safe to spend: both come out of the same money, and the app never shows them as a sum.
- `cards`: Card[] (spending baskets, bills before payday, and more later).
- `reviews`: Card[] of type `review` (section 3) with **at most one item**: the customer's pending review, if any. The app hides the section when the list is empty. Server rules:
  - **One at a time:** a pending review is served again, never created again. A new one is created only after the previous one is answered or has expired (7 days after creation). The first overview creates it (with #196, also the first `/api/ask` answer, if that comes first); later requests serve the same pending review.
  - **Undo after the 7 days** closes the review, and the purchase goes back to the basket the rules give it (section 10.1).
  - **Weekly limit:** at most 3 reviews are created per customer per calendar week (Monday to Sunday, Helsinki time, wall clock, not `DEMO_TODAY`).
  - A transaction is never asked about twice.
  - Health and other sensitive purchases are never asked about.
  - **While a review is pending,** its purchase is in the basket state `unclassified` ("Waiting for your answer"; Finnish "Odottaa vastaustasi"). That means no basket total, not the reserve for unexpected necessities, and, as a one-off, not the everyday run rate. Breakdowns then show a fourth item with key `unclassified`. The three basket keys stay the only answer options.
  - When the review expires unanswered, the purchase returns to the basket the rules give it.
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
    "subtitle": "1–7 Oct 2026",
    "evidence_ref": "ev_s2t4w6y8a0c2",
    "estimate": {
      "label": "Estimate",
      "text": "Your balance minus bills, usual essentials and a small cushion until payday, spread over the days to payday. It is also capped by your usual monthly budget after your savings goal is set aside first."
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
      },
      {
        "value": 430.0, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.savings_goal_eur@1", "evidence_ref": "ev_got7w9y1a3c5",
        "label": "Set aside first each month", "display": "€430.00 a month"
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
  "safe_to_save": {
    "card_id": "card_save_02",
    "type": "safe_to_save",
    "title": "Safe to save",
    "subtitle": "You could set aside about €430.00 a month on top of spending about €184.68 a week.",
    "evidence_ref": "ev_ai2m4o6n8t0h",
    "estimate": {
      "label": "Estimate",
      "text": "A typical month of your last six: income minus bills, saving you set up, usual essentials, a reserve for unexpected costs and your usual everyday spending."
    },
    "monthly": {
      "value": 431.58, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_ai2m4o6n8t0h",
      "label": "Typically left each month", "display": "€431.58 a month"
    },
    "monthly_components": [
      {
        "key": "free_month",
        "label": "Left after bills, essentials and the reserve",
        "operation": "add",
        "amount": {
          "value": 1080.55, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.free_month_eur@1", "evidence_ref": "ev_ai4f6m8o0n2t",
          "label": "Free in a typical month", "display": "€1,080.55 a month"
        }
      },
      {
        "key": "everyday_month",
        "label": "Usual everyday spending",
        "operation": "subtract",
        "amount": {
          "value": 648.97, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.everyday_month_eur@1", "evidence_ref": "ev_ai5e7v9m1o3n",
          "label": "Everyday spending in a typical month", "display": "€648.97 a month"
        }
      }
    ],
    "stock": {
      "value": 75.92, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_ai1s3a5v7e9n",
      "label": "In your account beyond what you need until payday", "display": "€75.92"
    },
    "stock_explanation": "Money in your account beyond what you need until payday, after bills, reserves, a small cushion and your usual everyday spending.",
    "stock_components": [
      {
        "key": "free_until_payday",
        "label": "Free until payday",
        "operation": "add",
        "amount": {
          "value": 395.74, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_s4t6w8y0a2c4",
          "label": "Free until payday", "display": "€395.74"
        }
      },
      {
        "key": "everyday_until_payday",
        "label": "Usual everyday spending until payday",
        "operation": "subtract",
        "amount": {
          "value": 319.82, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.everyday_until_payday_eur@1", "evidence_ref": "ev_ai3e5v7d9y1p",
          "label": "Everyday spending until payday", "display": "€319.82"
        }
      }
    ],
    "reason": null,
    "actions": [
      { "type": "open_evidence", "label": "How is this calculated?", "evidence_ref": "ev_ai2m4o6n8t0h" },
      { "type": "open_host_screen", "label": "See monthly saving in S-mobiili", "target": "monthly_saving" }
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
  "reviews": [],
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

The same overview when safe to spend cannot be computed for a known reason: `hero` is `null`, and the rest is served as usual (shortened here to the first card):

<!-- example: overview.response_no_hero -->
```json
{
  "customer_id": "CUST00042",
  "as_of": "2026-09-30",
  "language": "en",
  "greeting": "Hi Aino",
  "ai_disclosure": "Explanations are written by AI. The numbers are calculated from your transactions.",
  "hero": null,
  "safe_to_save": {
    "card_id": "card_save_02",
    "type": "safe_to_save",
    "title": "Safe to save",
    "subtitle": "You could set aside about €430.00 a month on top of spending about €184.68 a week.",
    "evidence_ref": "ev_ai2m4o6n8t0h",
    "estimate": {
      "label": "Estimate",
      "text": "A typical month of your last six: income minus bills, saving you set up, usual essentials, a reserve for unexpected costs and your usual everyday spending."
    },
    "monthly": {
      "value": 431.58,
      "unit": "eur_per_month",
      "period": {
        "start": "2026-04-01",
        "end": "2026-09-30",
        "label": "Apr-Sep 2026"
      },
      "method": "safe_to_spend.safe_to_save_monthly_eur@1",
      "evidence_ref": "ev_ai2m4o6n8t0h",
      "label": "Typically left each month",
      "display": "€431.58 a month"
    },
    "monthly_components": [
      {
        "key": "free_month",
        "label": "Left after bills, essentials and the reserve",
        "operation": "add",
        "amount": {
          "value": 1080.55,
          "unit": "eur_per_month",
          "period": {
            "start": "2026-04-01",
            "end": "2026-09-30",
            "label": "Apr-Sep 2026"
          },
          "method": "safe_to_spend.free_month_eur@1",
          "evidence_ref": "ev_ai4f6m8o0n2t",
          "label": "Free in a typical month",
          "display": "€1,080.55 a month"
        }
      },
      {
        "key": "everyday_month",
        "label": "Usual everyday spending",
        "operation": "subtract",
        "amount": {
          "value": 648.97,
          "unit": "eur_per_month",
          "period": {
            "start": "2026-04-01",
            "end": "2026-09-30",
            "label": "Apr-Sep 2026"
          },
          "method": "safe_to_spend.everyday_month_eur@1",
          "evidence_ref": "ev_ai5e7v9m1o3n",
          "label": "Everyday spending in a typical month",
          "display": "€648.97 a month"
        }
      }
    ],
    "stock": {
      "value": 75.92,
      "unit": "eur",
      "period": {
        "start": "2026-10-01",
        "end": "2026-10-15",
        "label": "Until payday on 15 Oct"
      },
      "method": "safe_to_spend.safe_to_save_eur@1",
      "evidence_ref": "ev_ai1s3a5v7e9n",
      "label": "In your account beyond what you need until payday",
      "display": "€75.92"
    },
    "stock_explanation": "Money in your account beyond what you need until payday, after bills, reserves, a small cushion and your usual everyday spending.",
    "stock_components": [
      {
        "key": "free_until_payday",
        "label": "Free until payday",
        "operation": "add",
        "amount": {
          "value": 395.74,
          "unit": "eur",
          "period": {
            "start": "2026-10-01",
            "end": "2026-10-15",
            "label": "Until payday on 15 Oct"
          },
          "method": "safe_to_spend.free_until_payday_eur@1",
          "evidence_ref": "ev_s4t6w8y0a2c4",
          "label": "Free until payday",
          "display": "€395.74"
        }
      },
      {
        "key": "everyday_until_payday",
        "label": "Usual everyday spending until payday",
        "operation": "subtract",
        "amount": {
          "value": 319.82,
          "unit": "eur",
          "period": {
            "start": "2026-10-01",
            "end": "2026-10-15",
            "label": "Until payday on 15 Oct"
          },
          "method": "safe_to_spend.everyday_until_payday_eur@1",
          "evidence_ref": "ev_ai3e5v7d9y1p",
          "label": "Everyday spending until payday",
          "display": "€319.82"
        }
      }
    ],
    "reason": null,
    "actions": [
      {
        "type": "open_evidence",
        "label": "How is this calculated?",
        "evidence_ref": "ev_ai2m4o6n8t0h"
      },
      {
        "type": "open_host_screen",
        "label": "See monthly saving in S-mobiili",
        "target": "monthly_saving"
      }
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
        "value": 2211.01,
        "unit": "eur_per_month",
        "period": {
          "start": "2026-04-01",
          "end": "2026-09-30",
          "label": "Apr-Sep 2026"
        },
        "method": "spender_profile.spend_month_eur@1",
        "evidence_ref": "ev_k4m6p8r0t2v4",
        "label": "Total spending",
        "display": "€2,211.01 a month"
      },
      "comparison": null,
      "items": [
        {
          "key": "regular_essentials",
          "label": "Regular essentials",
          "amount": {
            "value": 1180.21,
            "unit": "eur_per_month",
            "period": {
              "start": "2026-04-01",
              "end": "2026-09-30",
              "label": "Apr-Sep 2026"
            },
            "method": "baskets.month_avg_eur@1",
            "evidence_ref": "ev_br1a3c5e7g9i",
            "label": "Regular essentials",
            "display": "€1,180.21 a month"
          },
          "share": {
            "value": 53.4,
            "unit": "percent",
            "period": {
              "start": "2026-04-01",
              "end": "2026-09-30",
              "label": "Apr-Sep 2026"
            },
            "method": "baskets.share_pct@1",
            "evidence_ref": "ev_bs1a3c5e7g9i",
            "label": "Share of spending",
            "display": "53.4%"
          },
          "change": null,
          "flags": []
        },
        {
          "key": "unexpected_necessities",
          "label": "Unexpected necessities",
          "amount": {
            "value": 340.5,
            "unit": "eur_per_month",
            "period": {
              "start": "2026-04-01",
              "end": "2026-09-30",
              "label": "Apr-Sep 2026"
            },
            "method": "baskets.month_avg_eur@1",
            "evidence_ref": "ev_bi2b4d6f8h0j",
            "label": "Unexpected necessities",
            "display": "€340.50 a month"
          },
          "share": {
            "value": 15.4,
            "unit": "percent",
            "period": {
              "start": "2026-04-01",
              "end": "2026-09-30",
              "label": "Apr-Sep 2026"
            },
            "method": "baskets.share_pct@1",
            "evidence_ref": "ev_bt2b4d6f8h0j",
            "label": "Share of spending",
            "display": "15.4%"
          },
          "change": null,
          "flags": []
        },
        {
          "key": "everyday_spending",
          "label": "Everyday spending",
          "amount": {
            "value": 690.3,
            "unit": "eur_per_month",
            "period": {
              "start": "2026-04-01",
              "end": "2026-09-30",
              "label": "Apr-Sep 2026"
            },
            "method": "baskets.month_avg_eur@1",
            "evidence_ref": "ev_bl3c5e7g9i1k",
            "label": "Everyday spending",
            "display": "€690.30 a month"
          },
          "share": {
            "value": 31.2,
            "unit": "percent",
            "period": {
              "start": "2026-04-01",
              "end": "2026-09-30",
              "label": "Apr-Sep 2026"
            },
            "method": "baskets.share_pct@1",
            "evidence_ref": "ev_bu3c5e7g9i1k",
            "label": "Share of spending",
            "display": "31.2%"
          },
          "change": null,
          "flags": []
        }
      ],
      "actions": [
        {
          "type": "ask",
          "label": "What is in everyday spending?",
          "prompt": "What is in my everyday spending?"
        }
      ]
    }
  ],
  "reviews": [],
  "insights": [],
  "suggested_questions": [
    "Where did my money go?",
    "What kind of spender am I?",
    "What can I safely spend this week?",
    "How could I save more?"
  ]
}
```

Sanna's overview while her review is pending (values from the dataset, `metrics.md` section 1.1):
- the Home & Tech purchase is `unclassified` and outside the reserve, so safe to spend, after the savings goal of 360 a month (`metrics.md` section 3, #391), is 138.79;
- the review card asks about the purchase.

This is the demo's starting point. Answering "needed" moves safe to spend down to 97.46 (section 10); the savings goal stays 360.

<!-- example: overview.response_pending -->
```json
{
  "customer_id": "CUST00860",
  "as_of": "2026-09-30",
  "language": "en",
  "greeting": "Hi Sanna",
  "ai_disclosure": "Explanations are written by AI. The numbers are calculated from your transactions.",
  "hero": {
    "card_id": "card_sts_02",
    "type": "metric",
    "title": "Safe to spend in the next 7 days",
    "subtitle": "1–7 Oct 2026",
    "evidence_ref": "ev_sa4s6t8s0p2d",
    "estimate": {
      "label": "Estimate",
      "text": "Your balance minus bills, usual essentials and a small cushion until payday, spread over the days to payday. It is also capped by your usual monthly budget after your savings goal is set aside first."
    },
    "status": "ok",
    "primary": {
      "value": 138.79, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
      "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
      "label": "Safe to spend", "display": "€138.79"
    },
    "secondary": [
      {
        "value": 12656.12, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_pn1f3r5e7e9u",
        "label": "Free until payday", "display": "€12,656.12"
      },
      {
        "value": 5906.19, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.balance_limit_7d_eur@1", "evidence_ref": "ev_pn7b9a1l3i5m",
        "label": "Your balance allows", "display": "€5,906.19"
      },
      {
        "value": 138.79, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.budget_limit_7d_eur@1", "evidence_ref": "ev_pn8b0u2d4g6t",
        "label": "Your monthly budget allows", "display": "€138.79"
      },
      {
        "value": 360.0, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.savings_goal_eur@1", "evidence_ref": "ev_go8b0u2d4g6t",
        "label": "Set aside first each month", "display": "€360.00 a month"
      }
    ],
    "comparison": null,
    "components": [
      {
        "key": "balance",
        "label": "Money on your account",
        "operation": "add",
        "amount": {
          "value": 14276.35, "unit": "eur",
          "period": { "start": "2026-09-30", "end": "2026-09-30", "label": "30 Sep 2026" },
          "method": "safe_to_spend.balance_eur@1", "evidence_ref": "ev_pn9b1a3l5a7n",
          "label": "Balance", "display": "€14,276.35"
        }
      },
      {
        "key": "bills_due",
        "label": "Bills due before payday",
        "operation": "subtract",
        "amount": {
          "value": 928.5, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.bills_due_eur@1", "evidence_ref": "ev_pn0b2i4l6l8s",
          "label": "Bills before payday", "display": "€928.50"
        }
      },
      {
        "key": "essentials_reserve",
        "label": "Usual essentials until payday",
        "operation": "subtract",
        "amount": {
          "value": 423.99, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.essentials_reserve_eur@1", "evidence_ref": "ev_pn2e4s6s8e0n",
          "label": "Essentials reserve", "display": "€423.99"
        }
      },
      {
        "key": "irregular_reserve",
        "label": "Reserve for unexpected necessities",
        "operation": "subtract",
        "amount": {
          "value": 167.74, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sa3i5r7r9e1g",
          "label": "Irregular reserve", "display": "€167.74"
        }
      },
      {
        "key": "cushion",
        "label": "Cushion",
        "operation": "subtract",
        "amount": {
          "value": 100.0, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.cushion_eur@1", "evidence_ref": "ev_sn7c9u1s3h5n",
          "label": "Cushion", "display": "€100.00"
        }
      }
    ],
    "actions": [
      { "type": "open_evidence", "label": "How is this calculated?", "evidence_ref": "ev_sa4s6t8s0p2d" }
    ]
  },
  "safe_to_save": {
    "card_id": "card_save_06",
    "type": "safe_to_save",
    "title": "Safe to save",
    "subtitle": "You could set aside about €360.00 a month on top of spending about €138.79 a week.",
    "evidence_ref": "ev_sa6m8o0n2t4h",
    "estimate": {
      "label": "Estimate",
      "text": "A typical month of your last six: income minus bills, saving you set up, usual essentials, a reserve for unexpected costs and your usual everyday spending."
    },
    "monthly": {
      "value": 364.31, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sa6m8o0n2t4h",
      "label": "Typically left each month", "display": "€364.31 a month"
    },
    "monthly_components": [
      {
        "key": "free_month",
        "label": "Left after bills, essentials and the reserve",
        "operation": "add",
        "amount": {
          "value": 963.49, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.free_month_eur@1", "evidence_ref": "ev_pn5f7m9o1n3t",
          "label": "Free in a typical month", "display": "€963.49 a month"
        }
      },
      {
        "key": "everyday_month",
        "label": "Usual everyday spending",
        "operation": "subtract",
        "amount": {
          "value": 599.18, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.everyday_month_eur@1", "evidence_ref": "ev_pn6e8v0m2o4n",
          "label": "Everyday spending in a typical month", "display": "€599.18 a month"
        }
      }
    ],
    "stock": {
      "value": 12360.83, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_sa5s7a9v1e3n",
      "label": "In your account beyond what you need until payday", "display": "€12,360.83"
    },
    "stock_explanation": "Money in your account beyond what you need until payday, after bills, reserves, a small cushion and your usual everyday spending.",
    "stock_components": [
      {
        "key": "free_until_payday",
        "label": "Free until payday",
        "operation": "add",
        "amount": {
          "value": 12656.12, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_pn1f3r5e7e9u",
          "label": "Free until payday", "display": "€12,656.12"
        }
      },
      {
        "key": "everyday_until_payday",
        "label": "Usual everyday spending until payday",
        "operation": "subtract",
        "amount": {
          "value": 295.28, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.everyday_until_payday_eur@1", "evidence_ref": "ev_pn4e6v8d0y2p",
          "label": "Everyday spending until payday", "display": "€295.28"
        }
      }
    ],
    "reason": null,
    "actions": [
      { "type": "open_evidence", "label": "How is this calculated?", "evidence_ref": "ev_sa6m8o0n2t4h" },
      { "type": "open_host_screen", "label": "See monthly saving in S-mobiili", "target": "monthly_saving" }
    ]
  },
  "cards": [
    {
      "card_id": "card_baskets_02",
      "type": "breakdown",
      "title": "Where your money goes in a typical month",
      "subtitle": "Monthly average, April to September 2026",
      "evidence_ref": "ev_pk1t3o5t7a9l",
      "estimate": null,
      "display_hint": "stacked_bar",
      "total": {
        "value": 3010.59, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "spender_profile.spend_month_eur@1", "evidence_ref": "ev_pk1t3o5t7a9l",
        "label": "Total spending", "display": "€3,010.59 a month"
      },
      "comparison": null,
      "items": [
        {
          "key": "regular_essentials",
          "label": "Regular essentials",
          "amount": {
            "value": 1889.04, "unit": "eur_per_month",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_pk2r4e6g8u0l",
            "label": "Regular essentials", "display": "€1,889.04 a month"
          },
          "share": {
            "value": 62.7, "unit": "percent",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.share_pct@1", "evidence_ref": "ev_pk3r5e7g9u1s",
            "label": "Share of spending", "display": "62.7%"
          },
          "change": null,
          "flags": []
        },
        {
          "key": "unexpected_necessities",
          "label": "Unexpected necessities",
          "amount": {
            "value": 341.08, "unit": "eur_per_month",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sa1u3n5e7x9p",
            "label": "Unexpected necessities", "display": "€341.08 a month"
          },
          "share": {
            "value": 11.3, "unit": "percent",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.share_pct@1", "evidence_ref": "ev_pk4u6n8e0x2s",
            "label": "Share of spending", "display": "11.3%"
          },
          "change": null,
          "flags": []
        },
        {
          "key": "everyday_spending",
          "label": "Everyday spending",
          "amount": {
            "value": 600.41, "unit": "eur_per_month",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sb2e4v6e8r0y",
            "label": "Everyday spending", "display": "€600.41 a month"
          },
          "share": {
            "value": 19.9, "unit": "percent",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.share_pct@1", "evidence_ref": "ev_pk5e7v9e1r3s",
            "label": "Share of spending", "display": "19.9%"
          },
          "change": null,
          "flags": []
        },
        {
          "key": "unclassified",
          "label": "Waiting for your answer",
          "amount": {
            "value": 180.07, "unit": "eur_per_month",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_pu1n3c5l7a9s",
            "label": "Waiting for your answer", "display": "€180.07 a month"
          },
          "share": {
            "value": 6.0, "unit": "percent",
            "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
            "method": "baskets.share_pct@1", "evidence_ref": "ev_pk6u8n0c2l4s",
            "label": "Share of spending", "display": "6.0%"
          },
          "change": null,
          "flags": []
        }
      ],
      "actions": [
        { "type": "ask", "label": "Where did my money go?", "prompt": "Where did my money go?" }
      ]
    }
  ],
  "reviews": [
    {
      "card_id": "card_review_01",
      "type": "review",
      "title": "One question about a large purchase",
      "subtitle": "Home & Tech, 28 September 2026",
      "evidence_ref": "ev_rv1x3z5b7d9f",
      "estimate": null,
      "tx_ref": "txr_k7m2q9w4z8c3v6b1",
      "date": "2026-09-28",
      "category": "Home & Tech",
      "merchant": { "alias": "store_a", "label": "Home and tech store A" },
      "amount": {
        "value": 1080.42, "unit": "eur",
        "period": { "start": "2026-09-28", "end": "2026-09-28", "label": "28 Sep 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_rv1x3z5b7d9f",
        "label": "Home & Tech purchase", "display": "€1,080.42"
      },
      "current_basket": { "key": "unclassified", "label": "Waiting for your answer" },
      "question": {
        "en": "€1,080.42 at Home & Tech on 28 September 2026 — needed, or your choice?",
        "fi": "1 080,42 € Koti ja tekniikka, 28.9.2026 — välttämätön hankinta vai oma valinta?"
      },
      "options": [
        {
          "basket": "unexpected_necessities",
          "label": { "en": "Needed", "fi": "Välttämätön" },
          "effect": {
            "en": "It counts as an unexpected necessity. Sentti keeps a bigger reserve for surprises like this, so your safe to spend goes down.",
            "fi": "Se lasketaan välttämättömäksi yllätysmenoksi. Sentti varaa jatkossa enemmän rahaa tällaisiin yllätyksiin, joten turvallisesti käytettävissä oleva summa pienenee."
          }
        },
        {
          "basket": "everyday_spending",
          "label": { "en": "My choice", "fi": "Oma valinta" },
          "effect": {
            "en": "It counts as everyday spending. Your safe to spend stays the same; your everyday spending this month is higher than usual.",
            "fi": "Se lasketaan arkikulutukseksi. Turvallisesti käytettävissä oleva summa pysyy ennallaan, mutta arkikulutuksesi on tässä kuussa tavallista suurempi."
          }
        }
      ],
      "why": "Only you know what this purchase was. Your answer changes only how your own spending is grouped.",
      "actions": [
        { "type": "open_evidence", "label": "See the purchase", "evidence_ref": "ev_rv1x3z5b7d9f" }
      ]
    }
  ],
  "insights": [],
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
| `language` | `en`, `fi` or `auto` | Optional, default `auto`: the language is detected from the message, typed with or without ä and ö, and is English when unsure. Errors use the same language, except for a body that cannot be read or does not validate and for a message over 500 characters with `auto`: those are answered in English (section 1). |

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
| `card` | 0 to 3 times, as soon as a tool finishes | `card` (section 3). The server, never the model, may add one `review` card when the answer's tools touched the spike's basket or category. If a review is pending, it adds that one and never a second; otherwise it may create the next within the weekly limit of section 6. The card counts towards the 3 cards. |
| `numbers` | Before the first `delta` that uses them | `numbers`: a map from id to Number object |
| `delta` | 1 or more times | `text`: the next piece of the answer, with number tokens. A token is never split across two deltas. Append the pieces in order. In version 0.1 the core validates the whole answer first and then sends it sentence by sentence. Finer streaming may come later without a contract change. |
| `done` | Last, once, on success | `answer_id`, `outcome`, `text` (full, with tokens), `text_rendered`, `cited` (number ids used), `follow_ups` (string[]), `lesson` (`{key, title, text}` or null), `refusal` (`{kind, label}` or null), `clarify` (`{question, options}` or null), `warnings` (string[] of codes, see below), `actions` (Action[], since 0.3.3: see below), `ai_disclosure` (string or null, since 0.3.3: see below) |
| `error` | Last, once, on failure | `error`: `{code, message, retryable}`, the same envelope as an HTTP error (section 4) |

`outcome` is one of:
- `answered`: a normal answer. A plan was made (by the rules or the AI model), the tools ran, and the text passed the validator, whoever wrote it. When the AI model would have written the text and could not, the text is the template of the question and `warnings` contains `llm_unavailable`.
- `clarify`: the coach asks a question back.
- `refused`: out of scope; see `refusal.kind`.
- `fallback`: no usable answer could be built. Even the template's text failed the validator, so the core sends its fixed short text ("I could not find data for that question."). A recognised question whose template answered in the model's place is `answered` with `llm_unavailable`, never `fallback`. A question the rules did not recognise, with the AI model unavailable, gets the general clarifying question (`clarify` with `llm_unavailable`).

`actions` (since 0.3.3, #420) holds the answer's actions (section 3). A refusal, the rules' "I can't answer that one yet" answer (`outcome` `clarify`) and the "nothing found" fallback (`outcome` `fallback`) carry exactly one, the way to a human: `open_host_screen` with target `contact_bank`, label "Contact S-Pankki" / "Ota yhteyttä S-Pankkiin". Every other answer has `[]`, including the general clarifying question.

`ai_disclosure` (since 0.3.3, #420) is the overview's `ai_disclosure` text on the first answer of a conversation, so the app can show once that Sentti is an AI. It is `null` when that first answer is Sentti's introduction (the introduction says it), and on every later answer of the conversation. A new conversation (including after `conversation_reset`) discloses again.

`refusal.kind` is one of `investment_advice`, `credit_decision` (for example "Will the bank approve my mortgage?"), `out_of_scope`, `other_person_data` or `unsafe`.

`clarify` is set only when `outcome` is `clarify`:
- `question` repeats the text.
- `options` holds up to 3 short answers. The app shows them as chips, and a tap sends the option's text as the next message in the same conversation.

`warnings` holds codes the app may show as a small note:
- `llm_unavailable`: the AI model would have been used and was not, so the text is a template. Possible reasons: it is switched off, its daily budget is used up, it is paused after errors, the request's model window is used up, or it failed. The outcome stays `answered`, or `clarify` for a question the rules did not recognise, or `fallback` when even the template's text failed the validator.
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
  "warnings": [],
  "actions": [],
  "ai_disclosure": "Explanations are written by AI. The numbers are calculated from your transactions."
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
data: {"answer_id":"ans_7f3k9q2m","outcome":"answered","text":"September cost {{n1}}, which is {{n3}} more than August. Most of the increase is Travel at {{n5}}, which looks like a one-off, and Restaurants, up {{n8}}. A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust.","text_rendered":"September cost €2,315.60, which is €367.40 more than August. Most of the increase is Travel at €240.00, which looks like a one-off, and Restaurants, up €91.70. A one-off doesn't change your usual month, but eating out is a habit: small, frequent costs are the easiest place to adjust.","cited":["n1","n3","n5","n8"],"follow_ups":["What if I spend 20% less on restaurants?","How could I save more?","What can I safely spend this week?"],"lesson":{"key":"one_off_vs_habit","title":"One-offs and habits","text":"A one-off cost, like a trip, shows up once. A habit, like eating out, repeats every month, so a small change there adds up over a year."},"refusal":null,"clarify":null,"warnings":[],"actions":[],"ai_disclosure":"Explanations are written by AI. The numbers are calculated from your transactions."}
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
  "warnings": [],
  "actions": [],
  "ai_disclosure": "Selitykset kirjoittaa tekoäly. Luvut lasketaan tilitapahtumistasi."
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
  "warnings": [],
  "actions": [
    { "type": "open_host_screen", "label": "Contact S-Pankki", "target": "contact_bank" }
  ],
  "ai_disclosure": null
}
```

The same refusal as the first message of a conversation (`conversation_id` null) also carries the AI disclosure (#420):

<!-- example: ask.json.request_refusal_first -->
```json
{
  "customer_id": "CUST00042",
  "conversation_id": null,
  "message": "Should I put my savings into tech stocks?",
  "language": "auto"
}
```

<!-- example: ask.json.response_refusal_first -->
```json
{
  "answer_id": "ans_8d2f4h6k",
  "conversation_id": "conv_7m3p9r2t",
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
  "warnings": [],
  "actions": [
    { "type": "open_host_screen", "label": "Contact S-Pankki", "target": "contact_bank" }
  ],
  "ai_disclosure": "Explanations are written by AI. The numbers are calculated from your transactions."
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
  "warnings": [],
  "actions": [],
  "ai_disclosure": "Explanations are written by AI. The numbers are calculated from your transactions."
}
```

- **AI model unavailable:** if the AI model may not be used or fails after the tools have run, the core still sends the cards and the template text of the question, built from them. The outcome is `answered`, and `warnings` contains `llm_unavailable`. Two exceptions: a question the rules did not recognise gets the general clarifying question (`clarify`, with `llm_unavailable`), and when even the template's text fails the validator, the fixed short text goes out with outcome `fallback`.

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
| `language` | `en` or `fi` | Optional, default `en`. Error messages are in this language too, once the body validates. A body that cannot be read or does not validate is answered in the language of the `lang` query parameter, else in English (section 1). |

| `selection.kind` | `selection.value` | Example |
|---|---|---|
| `category` | A spending category (not an income, saving or transfer category) | `Restaurants` |
| `basket` | `regular_essentials`, `unexpected_necessities` or `everyday_spending` | `everyday_spending` |
| `mcc` | One or more MCC codes, comma-separated | `4121` (taxis) |
| `merchant` | A merchant id from a card. The AI model never sees merchant ids; the core maps them to the aliases the model uses. The customer's own alias (`store_a`) is accepted too. The response's `scenario.selection` echoes the merchant id. | `MRC-GRO-0035` |

`cut_pct` is a whole number from 1 to 100, sent as a JSON integer: `20.0` and `"20"` are 400 `invalid_request`. Regular essentials are never cut: their part of a selection is left out of the baseline and shown as `regular_excluded`. The response's `status` is one of:
- `estimate`: the normal case, for example everyday spending.
- `estimate_with_caveat`: the selection includes unexpected necessities; the card says these are needed costs that can only sometimes be reduced.
- `not_offered`: nothing in the selection can be cut, for example `Groceries`, which is all regular essentials. All savings are 0.

If the selection has no spending in the window at all, the response is 422 `invalid_scenario`. **Refused selections** get exactly the same 422 body, so that a Health refusal cannot be told apart from any other:
- Health or another sensitive selection, by category, MCC or merchant (rule R9);
- a category that is not spending, an unknown category or basket, or a malformed MCC;
- an unknown merchant, or one this customer has not used.

The basket `unexpected_necessities` is allowed. Its baseline includes the customer's own Health spending as part of the basket total, which the overview already shows; R9 forbids singling out sensitive spending, not the customer's own basket total.

<!-- example: whatif.error -->
```json
{
  "error": {
    "code": "invalid_scenario",
    "message": "This scenario cannot be calculated.",
    "retryable": false
  }
}
```

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

- `customer_id` must be the customer the evidence belongs to; otherwise the response is 403 `evidence_forbidden`. A `customer_id` that is not served (section 1) gets 404 `customer_not_found` before the ref is looked up.
- `limit` is 1 to 200 (default 50). `cursor` comes from the previous page.

`kind` decides which fields are filled:

| `kind` | Filled fields | Used for |
|---|---|---|
| `transactions` | `rows`, `row_count`, `reconciles`, `next_cursor` | Sums and counts over the customer's own transactions. |
| `composite` | `parts`: `{role, number: Number}`[] | Numbers computed from other numbers: changes, safe to spend, savings. Each part has its own `evidence_ref`, except a value from a bill (`bill_barcode@1` or `user_input@1`, section 11), which has none. |
| `metric` | `reconciles`; `rows` | Numbers read from a metric definition of `metrics.md` (safe to spend, safe to save, what-if, spender profile). The core re-runs the definition for the customer, and `reconciles: true` confirms that the re-run gives the same value. `rows` is always a list, empty today. `query` and `row_count` are `null`. |
| `peer_aggregate` | `parts`: `{role, number: Number}`[] for `peer_median`, `peer_p25`, `peer_p75` and `peer_n` (group size); `reconciles` | Peer benchmarks (#69). Shows group statistics only, never other customers' rows. The parts have `evidence_ref: null` (nothing further to open), and the group's level (section 3, `peer`) is named in the group size's label. `reconciles: true` confirms that a re-run of `06_peer_benchmark.sql` for the customer gives the same statistic. |
| `store_index` | `parts` | Store price levels. |

Values the user typed in (`method` = `user_input@1`) and values read from a bill's virtual barcode (`bill_barcode@1`) have `evidence_ref: null`, so they have no evidence to open.

In the overview's hero, `primary` (safe to spend) opens as a `composite`: the smaller of the two limits, each a part. The `bills_due` component opens as `transactions`, and the other components and the `secondary` numbers as `metric`. The `safe_to_save` card's numbers all open as `metric`.

Transaction rows are source records, not coach numbers. Their `amount` is a **decimal string with the bank sign** (`"-24.50"` means €24.50 out), a common banking-API convention that avoids rounding errors. This is one of the two exemptions from the Number rule (section 1). Each row also carries `display`: its amount formatted like a Number's display in the request language, with the bank sign (`-€24.50`, Finnish `-24,50 €`), so the app never formats a number; `amount` stays the exact decimal string. `reconciles: true` confirms that the rows add up to `number`. For transfers that are not card purchases, `merchant` and `mcc` are `null`.

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
      "currency": "EUR",
      "display": "-€24.50"
    },
    {
      "tx_id": "tx_2918101",
      "date": "2026-09-25",
      "time": "12:05",
      "category": "Restaurants",
      "merchant": { "id": "MRC-RES-0047", "label": "Restaurant B" },
      "mcc": "5814",
      "amount": "-11.90",
      "currency": "EUR",
      "display": "-€11.90"
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

A `metric` number (Sanna's budget limit for the next 7 days, from `core/metrics/03_safe_to_spend.sql`):

<!-- example: evidence.response_metric -->
```json
{
  "evidence_ref": "ev_b5l7m9t1d3g5",
  "kind": "metric",
  "language": "en",
  "title": "Your monthly budget allows, 1–7 Oct 2026",
  "number": {
    "value": 97.46, "unit": "eur",
    "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "1–7 Oct 2026" },
    "method": "safe_to_spend.budget_limit_7d_eur@1", "evidence_ref": "ev_b5l7m9t1d3g5",
    "label": "Your monthly budget allows", "display": "€97.46"
  },
  "method": {
    "id": "safe_to_spend.budget_limit_7d_eur@1",
    "name": "Your monthly budget allows",
    "summary": "Calculated by core/metrics/03_safe_to_spend.sql.",
    "doc": "docs/design/metrics.md#3-safe-to-spend"
  },
  "query": null,
  "rows": [],
  "row_count": null,
  "reconciles": true,
  "parts": [],
  "next_cursor": null,
  "privacy_note": "Only you can see this. Transactions are never sent to the AI model."
}
```

A `peer_aggregate` number (the median of the `card.peer` example). Its parts are group statistics without refs:

<!-- example: evidence.response_peer -->
```json
{
  "evidence_ref": "ev_q1s3u5w7y9a1",
  "kind": "peer_aggregate",
  "language": "en",
  "title": "Typical for similar people, 1 Apr – 30 Sep 2026",
  "number": {
    "value": 205.0, "unit": "eur_per_month",
    "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "1 Apr – 30 Sep 2026" },
    "method": "peer_benchmark.peer_median_month_eur@1", "evidence_ref": "ev_q1s3u5w7y9a1",
    "label": "Typical for similar people", "display": "€205.00 a month"
  },
  "method": {
    "id": "peer_benchmark.peer_median_month_eur@1",
    "name": "Typical for similar people",
    "summary": "Calculated by core/metrics/06_peer_benchmark.sql.",
    "doc": "docs/design/metrics.md#6-peer-benchmark"
  },
  "query": null,
  "rows": [],
  "row_count": null,
  "reconciles": true,
  "parts": [
    { "role": "peer_median", "number": {
      "value": 205.0, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "1 Apr – 30 Sep 2026" },
      "method": "peer_benchmark.peer_median_month_eur@1", "evidence_ref": null,
      "label": "Typical for similar people", "display": "€205.00 a month" } },
    { "role": "peer_p25", "number": {
      "value": 140.0, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "1 Apr – 30 Sep 2026" },
      "method": "peer_benchmark.peer_p25_month_eur@1", "evidence_ref": null,
      "label": "Lower quarter of similar people", "display": "€140.00 a month" } },
    { "role": "peer_p75", "number": {
      "value": 290.0, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "1 Apr – 30 Sep 2026" },
      "method": "peer_benchmark.peer_p75_month_eur@1", "evidence_ref": null,
      "label": "Upper quarter of similar people", "display": "€290.00 a month" } },
    { "role": "peer_n", "number": {
      "value": 23, "unit": "count",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "1 Apr – 30 Sep 2026" },
      "method": "peer_benchmark.peer_n@1", "evidence_ref": null,
      "label": "Similar people compared (same age group and postal area)", "display": "23" } }
  ],
  "next_cursor": null,
  "privacy_note": "Only group statistics are shown here, never another customer's transactions."
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

## 10. `POST /api/baskets/label`

The customer's answer to a `review` card. **The app calls it when the customer taps an option.** It is not a tool of the AI model, and the model can never write data (design doc, section 7.8, rule R6).

### 10.1 Request

| Field | Type | Meaning |
|---|---|---|
| `customer_id` | string | Persona. |
| `tx_ref` | string | From the `review` card. |
| `basket` | `unexpected_necessities`, `everyday_spending` or `null` | The chosen option. `null` undoes the label. |
| `language` | `en` or `fi` | Optional, default `en`. Error messages are in this language too, once the body validates. A body that cannot be read or does not validate is answered in the language of the `lang` query parameter, else in English (section 1). |

**What the answers do** (`metrics.md` section 1.1). While the review is pending, the purchase is `unclassified`: in no basket and not in the reserve. No answer raises safe to spend above the value shown while the question was pending. Undo and changing the answer only move between the documented states.
- **"Needed"** (`unexpected_necessities`): the purchase joins that basket and its reserve, so the reserve grows and safe to spend goes **down**. Sanna: 138.79 → 97.46.
- **"My choice"** (`everyday_spending`): the purchase joins everyday spending, and safe to spend **stays the same**. It stays a one-off, outside the everyday run rate.
- **The message is the real effect** (#382): it is built from the overview's numbers before and after the answer, never a fixed promise. When safe to spend moves, it says from what to what and where the purchase went. When it does not, it says where the purchase went and then either what safe to save did or why safe to spend stays (which limit binds). Two sentences at most.

**Rules:**
- **Idempotent:** sending the same answer again returns 200 with `changed: false` and an empty `changes` list.
- **Changing the answer:** a different `basket` replaces the label.
- **Undo:** `basket: null` removes the label. If the review was created less than 7 days ago, the purchase goes back to `unclassified` and the review is pending again. Otherwise the review closes, and the purchase goes back to the basket the rules give it. Either way, the transaction is never asked about in a new review.
- **Expiry:**
  - A pending review expires 7 days after creation; an answered review does not expire.
  - A review can be answered, changed or undone only while it is pending (not expired) or answered.
  - Once a pending review has expired, its `tx_ref` is no longer valid: the call returns 404 `tx_ref_not_found`, and the purchase stays in its rule-based basket. There are no late answers.
- **What can be labelled:** only reviewable spikes have a `tx_ref`, so a Health or other sensitive purchase can never be labelled.

**Response:**
- `label`: `{basket, label, labelled_at}`, or `null` after an undo.
- `review_state`: `answered`, `pending` (undone while open) or `closed` (undone after expiry).
- `changed`: whether anything changed.
- `message`: `{text, text_rendered, numbers}`. It is a localised confirmation whose numbers are tokens, as in section 2.4.
- `changes`: the overview numbers that moved, each `{key, label, before: Number, after: Number}`. It is empty when `changed` is false. Before and after have different `evidence_ref`s, because evidence keeps resolving to the numbers as they were.
- `effect` (#382): `{items, text, text_rendered, numbers}`, or `null` when `changed` is false.
  - `items`: the headline numbers, each `{key, label, before: Number, after: Number}` with ids: `safe_to_spend`, `safe_to_save` (the overview's monthly figure, when the overview shows it), `irregular_reserve`, and the basket the purchase moved into (`unclassified` after an undo while open). Every item is listed even when its value did not move, so the app can show "no change". `before` and `after` are exactly the overview's numbers before and after, with their evidence refs.
  - `text`, `text_rendered`, `numbers`: the effect as one or two sentences with number tokens (section 2.4), the same text as `message`. The app shows it in the card's confirmation.
  - An undo returns the same structure with the sides swapped.
- **Rounding:** derived figures are computed from unrounded values and rounded once, so a figure can differ by 0.01 from the same sum of displayed figures (for example 12,360.83 against 12,656.12 − 295.28 = 12,360.84).
- `refetch`: what to reload for everything else.

**Errors** (section 4):
- 400 `invalid_request`: a malformed body, including a `basket` that is not one of the three basket keys or `null`;
- 404 `customer_not_found`;
- 404 `tx_ref_not_found`: an unknown ref, the ref of an expired review, **or one of another customer**. The same answer for all three, so nobody can probe for other customers' refs (R4);
- 422 `basket_not_allowed`: a valid basket key that is not one of the review's two options, for example `regular_essentials`;
- 429 `rate_limited` (#144): the label write is rate-limited; the response carries `Retry-After`.

### 10.2 Examples

Sanna answers "needed" for the Home & Tech purchase of `card.review`. This is the demo path; the bank's own example is a washing machine. The values are from the dataset (`metrics.md` section 1.1). Before the answer, the purchase is `unclassified` and safe to spend is 138.79. After it, the purchase is in unexpected necessities, the reserve is 88.56 higher, and safe to spend is 97.46.

<!-- example: label.request -->
```json
{ "customer_id": "CUST00860", "tx_ref": "txr_k7m2q9w4z8c3v6b1", "basket": "unexpected_necessities", "language": "en" }
```

<!-- example: label.response -->
```json
{
  "customer_id": "CUST00860",
  "as_of": "2026-09-30",
  "language": "en",
  "tx_ref": "txr_k7m2q9w4z8c3v6b1",
  "label": { "basket": "unexpected_necessities", "label": "Unexpected necessities", "labelled_at": "2026-11-14T10:32:05+02:00" },
  "review_state": "answered",
  "changed": true,
  "message": {
    "text": "Your safe to spend this week goes from {{n1}} to {{n2}}: {{n9}} now counts as an unexpected necessity, so the reserve grows.",
    "text_rendered": "Your safe to spend this week goes from €138.79 to €97.46: €1,080.42 now counts as an unexpected necessity, so the reserve grows.",
    "numbers": {
      "n1": {
        "id": "n1", "value": 138.79, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
        "label": "Safe to spend", "display": "€138.79"
      },
      "n2": {
        "id": "n2", "value": 97.46, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sb4s6t8s0p2d",
        "label": "Safe to spend", "display": "€97.46"
      },
      "n9": {
        "id": "n9", "value": 1080.42, "unit": "eur",
        "period": { "start": "2026-09-28", "end": "2026-09-28", "label": "28 Sep 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_rv1x3z5b7d9f",
        "label": "Home & Tech purchase", "display": "€1,080.42"
      }
    }
  },
  "changes": [
    {
      "key": "unclassified",
      "label": "Waiting for your answer, monthly average",
      "before": {
        "value": 180.07, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_pu1n3c5l7a9s",
        "label": "Waiting for your answer, monthly average", "display": "€180.07 a month"
      },
      "after": {
        "value": 0.0, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_na0u2n4c6l8a",
        "label": "Waiting for your answer, monthly average", "display": "€0.00 a month"
      }
    },
    {
      "key": "unexpected_necessities",
      "label": "Unexpected necessities, monthly average",
      "before": {
        "value": 341.08, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sa1u3n5e7x9p",
        "label": "Unexpected necessities, monthly average", "display": "€341.08 a month"
      },
      "after": {
        "value": 521.15, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sb1u3n5e7x9p",
        "label": "Unexpected necessities, monthly average", "display": "€521.15 a month"
      }
    },
    {
      "key": "irregular_reserve",
      "label": "Reserve for unexpected necessities",
      "before": {
        "value": 167.74, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sa3i5r7r9e1g",
        "label": "Reserve for unexpected necessities", "display": "€167.74"
      },
      "after": {
        "value": 256.3, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sb3i5r7r9e1g",
        "label": "Reserve for unexpected necessities", "display": "€256.30"
      }
    },
    {
      "key": "safe_to_spend",
      "label": "Safe to spend",
      "before": {
        "value": 138.79, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
        "label": "Safe to spend", "display": "€138.79"
      },
      "after": {
        "value": 97.46, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sb4s6t8s0p2d",
        "label": "Safe to spend", "display": "€97.46"
      }
    },
    {
      "key": "safe_to_save_monthly",
      "label": "Typically left each month",
      "before": {
        "value": 364.31, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sa6m8o0n2t4h",
        "label": "Typically left each month", "display": "€364.31 a month"
      },
      "after": {
        "value": 184.61, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sn3m5o7n9t1h",
        "label": "Typically left each month", "display": "€184.61 a month"
      }
    },
    {
      "key": "safe_to_save",
      "label": "Left over in your account",
      "before": {
        "value": 12360.83, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_sa5s7a9v1e3n",
        "label": "Left over in your account", "display": "€12,360.83"
      },
      "after": {
        "value": 12272.28, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_sn2s4a6v8e0n",
        "label": "Left over in your account", "display": "€12,272.28"
      }
    }
  ],
  "effect": {
    "items": [
      {
        "key": "safe_to_spend", "label": "Safe to spend",
        "before": {
          "id": "n1", "value": 138.79, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
          "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
          "label": "Safe to spend", "display": "€138.79"
        },
        "after": {
          "id": "n2", "value": 97.46, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
          "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sb4s6t8s0p2d",
          "label": "Safe to spend", "display": "€97.46"
        }
      },
      {
        "key": "safe_to_save", "label": "Typically left each month",
        "before": {
          "id": "n3", "value": 364.31, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sa6m8o0n2t4h",
          "label": "Typically left each month", "display": "€364.31 a month"
        },
        "after": {
          "id": "n4", "value": 184.61, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sn3m5o7n9t1h",
          "label": "Typically left each month", "display": "€184.61 a month"
        }
      },
      {
        "key": "irregular_reserve", "label": "Reserve for unexpected necessities",
        "before": {
          "id": "n5", "value": 167.74, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sa3i5r7r9e1g",
          "label": "Reserve for unexpected necessities", "display": "€167.74"
        },
        "after": {
          "id": "n6", "value": 256.3, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sb3i5r7r9e1g",
          "label": "Reserve for unexpected necessities", "display": "€256.30"
        }
      },
      {
        "key": "unexpected_necessities", "label": "Unexpected necessities, monthly average",
        "before": {
          "id": "n7", "value": 341.08, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sa1u3n5e7x9p",
          "label": "Unexpected necessities, monthly average", "display": "€341.08 a month"
        },
        "after": {
          "id": "n8", "value": 521.15, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sb1u3n5e7x9p",
          "label": "Unexpected necessities, monthly average", "display": "€521.15 a month"
        }
      }
    ],
    "text": "Your safe to spend this week goes from {{n1}} to {{n2}}: {{n9}} now counts as an unexpected necessity, so the reserve grows.",
    "text_rendered": "Your safe to spend this week goes from €138.79 to €97.46: €1,080.42 now counts as an unexpected necessity, so the reserve grows.",
    "numbers": {
      "n1": {
        "id": "n1", "value": 138.79, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
        "label": "Safe to spend", "display": "€138.79"
      },
      "n2": {
        "id": "n2", "value": 97.46, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sb4s6t8s0p2d",
        "label": "Safe to spend", "display": "€97.46"
      },
      "n9": {
        "id": "n9", "value": 1080.42, "unit": "eur",
        "period": { "start": "2026-09-28", "end": "2026-09-28", "label": "28 Sep 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_rv1x3z5b7d9f",
        "label": "Home & Tech purchase", "display": "€1,080.42"
      }
    }
  },
  "refetch": ["/api/overview/CUST00860"]
}
```

If she answers "My choice" instead, everyday spending gains the purchase and safe to spend stays at 138.79:

<!-- example: label.request_wanted -->
```json
{ "customer_id": "CUST00860", "tx_ref": "txr_k7m2q9w4z8c3v6b1", "basket": "everyday_spending", "language": "en" }
```

<!-- example: label.response_wanted -->
```json
{
  "customer_id": "CUST00860",
  "as_of": "2026-09-30",
  "language": "en",
  "tx_ref": "txr_k7m2q9w4z8c3v6b1",
  "label": { "basket": "everyday_spending", "label": "Everyday spending", "labelled_at": "2026-11-14T10:32:05+02:00" },
  "review_state": "answered",
  "changed": true,
  "message": {
    "text": "{{n9}} now counts as everyday spending. This does not change this week's safe to spend: your monthly budget, not this purchase, sets the limit.",
    "text_rendered": "€1,080.42 now counts as everyday spending. This does not change this week's safe to spend: your monthly budget, not this purchase, sets the limit.",
    "numbers": {
      "n9": {
        "id": "n9", "value": 1080.42, "unit": "eur",
        "period": { "start": "2026-09-28", "end": "2026-09-28", "label": "28 Sep 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_rv1x3z5b7d9f",
        "label": "Home & Tech purchase", "display": "€1,080.42"
      }
    }
  },
  "changes": [
    {
      "key": "unclassified",
      "label": "Waiting for your answer, monthly average",
      "before": {
        "value": 180.07, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_pu1n3c5l7a9s",
        "label": "Waiting for your answer, monthly average", "display": "€180.07 a month"
      },
      "after": {
        "value": 0.0, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_wa0u2n4c6l8a",
        "label": "Waiting for your answer, monthly average", "display": "€0.00 a month"
      }
    },
    {
      "key": "everyday_spending",
      "label": "Everyday spending, monthly average",
      "before": {
        "value": 600.41, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sb2e4v6e8r0y",
        "label": "Everyday spending, monthly average", "display": "€600.41 a month"
      },
      "after": {
        "value": 780.48, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sa2e4v6e8r0y",
        "label": "Everyday spending, monthly average", "display": "€780.48 a month"
      }
    }
  ],
  "effect": {
    "items": [
      {
        "key": "safe_to_spend", "label": "Safe to spend",
        "before": {
          "id": "n1", "value": 138.79, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
          "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
          "label": "Safe to spend", "display": "€138.79"
        },
        "after": {
          "id": "n2", "value": 138.79, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
          "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_wc4s6t8s0p2d",
          "label": "Safe to spend", "display": "€138.79"
        }
      },
      {
        "key": "safe_to_save", "label": "Typically left each month",
        "before": {
          "id": "n3", "value": 364.31, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sa6m8o0n2t4h",
          "label": "Typically left each month", "display": "€364.31 a month"
        },
        "after": {
          "id": "n4", "value": 364.31, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_wc6m8o0n2t4h",
          "label": "Typically left each month", "display": "€364.31 a month"
        }
      },
      {
        "key": "irregular_reserve", "label": "Reserve for unexpected necessities",
        "before": {
          "id": "n5", "value": 167.74, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sa3i5r7r9e1g",
          "label": "Reserve for unexpected necessities", "display": "€167.74"
        },
        "after": {
          "id": "n6", "value": 167.74, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_wc3i5r7r9e1g",
          "label": "Reserve for unexpected necessities", "display": "€167.74"
        }
      },
      {
        "key": "everyday_spending", "label": "Everyday spending, monthly average",
        "before": {
          "id": "n7", "value": 600.41, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sb2e4v6e8r0y",
          "label": "Everyday spending, monthly average", "display": "€600.41 a month"
        },
        "after": {
          "id": "n8", "value": 780.48, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sa2e4v6e8r0y",
          "label": "Everyday spending, monthly average", "display": "€780.48 a month"
        }
      }
    ],
    "text": "{{n9}} now counts as everyday spending. This does not change this week's safe to spend: your monthly budget, not this purchase, sets the limit.",
    "text_rendered": "€1,080.42 now counts as everyday spending. This does not change this week's safe to spend: your monthly budget, not this purchase, sets the limit.",
    "numbers": {
      "n9": {
        "id": "n9", "value": 1080.42, "unit": "eur",
        "period": { "start": "2026-09-28", "end": "2026-09-28", "label": "28 Sep 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_rv1x3z5b7d9f",
        "label": "Home & Tech purchase", "display": "€1,080.42"
      }
    }
  },
  "refetch": ["/api/overview/CUST00860"]
}
```

The "needed" answer undone while the review is still open: the purchase is `unclassified` again, and the numbers return to the pending state:

<!-- example: label.request_undo -->
```json
{ "customer_id": "CUST00860", "tx_ref": "txr_k7m2q9w4z8c3v6b1", "basket": null, "language": "en" }
```

<!-- example: label.response_undo -->
```json
{
  "customer_id": "CUST00860",
  "as_of": "2026-09-30",
  "language": "en",
  "tx_ref": "txr_k7m2q9w4z8c3v6b1",
  "label": null,
  "review_state": "pending",
  "changed": true,
  "message": {
    "text": "Your safe to spend this week goes from {{n1}} to {{n2}}: {{n9}} is waiting for your answer again.",
    "text_rendered": "Your safe to spend this week goes from €97.46 to €138.79: €1,080.42 is waiting for your answer again.",
    "numbers": {
      "n1": {
        "id": "n1", "value": 97.46, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sb4s6t8s0p2d",
        "label": "Safe to spend", "display": "€97.46"
      },
      "n2": {
        "id": "n2", "value": 138.79, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
        "label": "Safe to spend", "display": "€138.79"
      },
      "n9": {
        "id": "n9", "value": 1080.42, "unit": "eur",
        "period": { "start": "2026-09-28", "end": "2026-09-28", "label": "28 Sep 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_rv1x3z5b7d9f",
        "label": "Home & Tech purchase", "display": "€1,080.42"
      }
    }
  },
  "changes": [
    {
      "key": "unclassified",
      "label": "Waiting for your answer, monthly average",
      "before": {
        "value": 0.0, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_na0u2n4c6l8a",
        "label": "Waiting for your answer, monthly average", "display": "€0.00 a month"
      },
      "after": {
        "value": 180.07, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_pu1n3c5l7a9s",
        "label": "Waiting for your answer, monthly average", "display": "€180.07 a month"
      }
    },
    {
      "key": "unexpected_necessities",
      "label": "Unexpected necessities, monthly average",
      "before": {
        "value": 521.15, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sb1u3n5e7x9p",
        "label": "Unexpected necessities, monthly average", "display": "€521.15 a month"
      },
      "after": {
        "value": 341.08, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_sa1u3n5e7x9p",
        "label": "Unexpected necessities, monthly average", "display": "€341.08 a month"
      }
    },
    {
      "key": "irregular_reserve",
      "label": "Reserve for unexpected necessities",
      "before": {
        "value": 256.3, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sb3i5r7r9e1g",
        "label": "Reserve for unexpected necessities", "display": "€256.30"
      },
      "after": {
        "value": 167.74, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sa3i5r7r9e1g",
        "label": "Reserve for unexpected necessities", "display": "€167.74"
      }
    },
    {
      "key": "safe_to_spend",
      "label": "Safe to spend",
      "before": {
        "value": 97.46, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sb4s6t8s0p2d",
        "label": "Safe to spend", "display": "€97.46"
      },
      "after": {
        "value": 138.79, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
        "label": "Safe to spend", "display": "€138.79"
      }
    },
    {
      "key": "safe_to_save_monthly",
      "label": "Typically left each month",
      "before": {
        "value": 184.61, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sn3m5o7n9t1h",
        "label": "Typically left each month", "display": "€184.61 a month"
      },
      "after": {
        "value": 364.31, "unit": "eur_per_month",
        "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
        "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sa6m8o0n2t4h",
        "label": "Typically left each month", "display": "€364.31 a month"
      }
    },
    {
      "key": "safe_to_save",
      "label": "Left over in your account",
      "before": {
        "value": 12272.28, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_sn2s4a6v8e0n",
        "label": "Left over in your account", "display": "€12,272.28"
      },
      "after": {
        "value": 12360.83, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
        "method": "safe_to_spend.safe_to_save_eur@1", "evidence_ref": "ev_sa5s7a9v1e3n",
        "label": "Left over in your account", "display": "€12,360.83"
      }
    }
  ],
  "effect": {
    "items": [
      {
        "key": "safe_to_spend", "label": "Safe to spend",
        "before": {
          "id": "n1", "value": 97.46, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
          "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sb4s6t8s0p2d",
          "label": "Safe to spend", "display": "€97.46"
        },
        "after": {
          "id": "n2", "value": 138.79, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
          "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
          "label": "Safe to spend", "display": "€138.79"
        }
      },
      {
        "key": "safe_to_save", "label": "Typically left each month",
        "before": {
          "id": "n3", "value": 184.61, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sn3m5o7n9t1h",
          "label": "Typically left each month", "display": "€184.61 a month"
        },
        "after": {
          "id": "n4", "value": 364.31, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "safe_to_spend.safe_to_save_monthly_eur@1", "evidence_ref": "ev_sa6m8o0n2t4h",
          "label": "Typically left each month", "display": "€364.31 a month"
        }
      },
      {
        "key": "irregular_reserve", "label": "Reserve for unexpected necessities",
        "before": {
          "id": "n5", "value": 256.3, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sb3i5r7r9e1g",
          "label": "Reserve for unexpected necessities", "display": "€256.30"
        },
        "after": {
          "id": "n6", "value": 167.74, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
          "method": "safe_to_spend.irregular_reserve_eur@1", "evidence_ref": "ev_sa3i5r7r9e1g",
          "label": "Reserve for unexpected necessities", "display": "€167.74"
        }
      },
      {
        "key": "unclassified", "label": "Waiting for your answer, monthly average",
        "before": {
          "id": "n7", "value": 0.0, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_na0u2n4c6l8a",
          "label": "Waiting for your answer, monthly average", "display": "€0.00 a month"
        },
        "after": {
          "id": "n8", "value": 180.07, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
          "method": "baskets.month_avg_eur@1", "evidence_ref": "ev_pu1n3c5l7a9s",
          "label": "Waiting for your answer, monthly average", "display": "€180.07 a month"
        }
      }
    ],
    "text": "Your safe to spend this week goes from {{n1}} to {{n2}}: {{n9}} is waiting for your answer again.",
    "text_rendered": "Your safe to spend this week goes from €97.46 to €138.79: €1,080.42 is waiting for your answer again.",
    "numbers": {
      "n1": {
        "id": "n1", "value": 97.46, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sb4s6t8s0p2d",
        "label": "Safe to spend", "display": "€97.46"
      },
      "n2": {
        "id": "n2", "value": 138.79, "unit": "eur",
        "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
        "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_sa4s6t8s0p2d",
        "label": "Safe to spend", "display": "€138.79"
      },
      "n9": {
        "id": "n9", "value": 1080.42, "unit": "eur",
        "period": { "start": "2026-09-28", "end": "2026-09-28", "label": "28 Sep 2026" },
        "method": "spending.total@1", "evidence_ref": "ev_rv1x3z5b7d9f",
        "label": "Home & Tech purchase", "display": "€1,080.42"
      }
    }
  },
  "refetch": ["/api/overview/CUST00860"]
}
```

<!-- example: label.error -->
```json
{
  "error": {
    "code": "basket_not_allowed",
    "message": "This answer is not one of the options for this question.",
    "retryable": false
  }
}
```

---

## 11. `POST /api/bill/explain`

The customer shows Sentti a bill (lasku) and gets it explained with their own data: who it is from, how much, when it is due, how it compares with what they usually pay this payee, and what paying it does to the hero's numbers. No AI model is called, and nothing is stored: like the what-if calculator, it is a read-only computation (#242).

Every number is one of these:
- read from the bill's virtual barcode and checked by code (`bill_barcode@1`);
- typed or confirmed by the user (`user_input@1`);
- computed from the customer's data by the existing metrics.

A language model never supplies a number of the explanation: a reading of a bill image (section 11.4) is only a proposal that the user confirms. **Sentti does not pay:** when the bill passes its checks, the response offers a payment draft that the app hands to the host app (section 11.3).

### 11.1 Request

| Field | Type | Meaning |
|---|---|---|
| `customer_id` | string | Persona. |
| `language` | `en` or `fi` | Optional, default `en`. Error messages are in this language too, once the body validates. A body that cannot be read or does not validate is answered in the language of the `lang` query parameter, else in English (section 1). |
| `barcode` | string or `null` | The bill's virtual barcode (virtuaaliviivakoodi): 54 digits, version 4 or 5. Spaces, non-breaking spaces and line breaks are ignored. At most 80 characters. |
| `payee` | string or `null` | Only beside `barcode`: the payee's name as printed on the bill, because the barcode carries no name. 1 to 70 characters. |
| `fields` | object or `null` | The bill's details as the user typed or confirmed them: `{payee, iban, reference, amount, due_date}`, all required (below). |

**Exactly one of `barcode` and `fields`** is set; the other is `null` or left out. An unknown field, or a text over its limit, is 400 `invalid_request`; unlike `/api/whatif`, this endpoint does not ignore unknown fields.

| `fields.` | Type | Meaning |
|---|---|---|
| `payee` | string | The payee's name, 1 to 70 characters. |
| `iban` | string | The payee's account, at most 42 characters; spaces are ignored. |
| `reference` | string | The reference number (viitenumero), national or `RF`, at most 35 characters; spaces are ignored. |
| `amount` | string | A decimal string in euros with at most two decimals, more than 0 and at most `100000.00`, for example `"145.00"`. Anything else is 400 `invalid_request`. |
| `due_date` | date | The due date (eräpäivä), exactly `YYYY-MM-DD` and a real date. A number, a timestamp or any other form is 400 `invalid_request`. |

**Texts are data.** `payee`, `iban` and `reference` are returned as data only: they are never interpreted, never used to build a query, and the payee's name as sent never appears inside a sentence of the response.

**A request the explanation cannot use is 422 `invalid_bill`.** Its error body has one more field than the envelope of section 4: `reason`, a stable code. `message` is a plain sentence for that reason in the request language, so the app can show it and fall back to the fields form. No field of a barcode that failed is returned.

| `reason` | When |
|---|---|
| `one_of_barcode_or_fields` | Both or neither of `barcode` and `fields`. |
| `payee_with_fields` | `payee` beside `fields` (the name goes inside `fields`). |
| `barcode_length` | The barcode does not have 54 digits. |
| `barcode_version` | The barcode is not version 4 or 5. |
| `barcode_chars` | The barcode has a character that is not a digit. |
| `barcode_check` | The IBAN or the reference inside the barcode fails its check. |
| `due_date` | The barcode's due date is not a real date. |
| `amount_missing` | The barcode carries no amount. |
| `due_date_missing` | The barcode carries no due date. |
| `amount_too_large` | The barcode's amount is over 100,000.00. |

**A failed check of a typed `iban` or `reference`, or a due date in the past, is not an error:** the response is a 200. A failed check shows in `checks` and `signals`, a past due date in `checks` and `warnings` (section 11.2).

A barcode, with the payee's name typed beside it:

<!-- example: bill.request -->
```json
{
  "customer_id": "CUST00042",
  "language": "en",
  "barcode": "421123456000007850008124000000000000000000001232261001",
  "payee": "Esimerkki Asunnot Oy",
  "fields": null
}
```

The details typed by the user, here with a reference number that fails its check:

<!-- example: bill.request_fields -->
```json
{
  "customer_id": "CUST00042",
  "language": "en",
  "barcode": null,
  "payee": null,
  "fields": {
    "payee": "Esimerkki Remontti Oy",
    "iban": "FI71 1234 5600 0098 76",
    "reference": "12345",
    "amount": "145.00",
    "due_date": "2026-10-20"
  }
}
```

A barcode whose reference fails its check:

<!-- example: bill.error -->
```json
{
  "error": {
    "code": "invalid_bill",
    "message": "This barcode does not pass its check. Compare it with the paper bill, or type the fields.",
    "retryable": false,
    "reason": "barcode_check"
  }
}
```

### 11.2 Response

| Field | Meaning |
|---|---|
| `bill` | The bill as the service read it:<br>- `source`: `barcode` or `fields`.<br>- `payee`: the name as sent, or `null` for a barcode without one.<br>- `iban` and `reference`: formatted for display (the IBAN in groups of four; a national reference in groups of five from the right, an `RF` reference in groups of four).<br>- `amount` (Number): `method` is `bill_barcode@1` for a barcode and `user_input@1` for `fields`; `evidence_ref` is `null`, because the number does not come from the customer's data; the period is the due date.<br>- `due_date`. |
| `checks` | `{iban, reference, due_date}`: `iban` and `reference` are `pass` or `fail` (the IBAN's mod-97 check; the reference's check digit, national or `RF`); `due_date` is `pass`, or `past` when it is before `as_of`. A barcode always gives `pass` for both, because a barcode that fails a check is 422. |
| `match` | Whether the payee is one of the customer's recurring bills (section 3, `bills`):<br>- `status`: `matched`, `not_matched`, or `no_payee` (a barcode sent without `payee`).<br>- `bill_id` and `label`: the matched bill's id and label, as in the bills card, else `null`.<br>- `text`: one sentence.<br>The match is exact after normalisation (case, spaces and punctuation are ignored). It compares the payee with the labels of the customer's recurring bills in both languages and with a fixed table of known payee names for each kind of recurring bill. A real bank knows the counterparty of earlier payments; the synthetic data has none, so this table stands in for it in the demo, with fictional companies only (the table below). There is no fuzzy matching. No match is a normal outcome. |
| `comparison` | A [Comparison](#23-comparison), only when `matched`, else `null`:<br>- `baseline`: the matched bill's `typical_month`, the same Number and `evidence_ref` as in the bills card.<br>- `change`: the bill's amount minus the typical amount, in euros, signed (`bill.vs_typical_eur@1`).<br>- `change_pct`: the same in percent of the typical amount (`bill.vs_typical_pct@1`), `null` when the typical amount is 0.<br>- `tone`: `worse` when the bill is higher, `better` when lower, `neutral` when equal. |
| `basket` | `{key, label, text}`. A matched bill: the matched bill's basket, `regular_essentials`. Any other bill: `unexpected_necessities`, as a suggestion, and the text says that it is not one of the customer's regular bills. Nothing is labelled or stored. |
| `safe_to_spend` | What paying the bill on time does to the hero's numbers (section 6), or `null` when safe to spend cannot be computed for a known reason (as the overview's `hero`). **The bill is applied to the balance side exactly as a bill due before payday is** (the `bills_due` component of the hero), and the hero's own computation runs again with that input. Nothing is subtracted from safe to spend directly. Fields:<br>- `effect`: one of three values, below.<br>- `next_payday`: a date.<br>- `reserved`: for `excess_only`, the matched bill's `due_until_payday`, the same Number as in the bills card; else `null`.<br>- `counted`: what the bill adds to the bills due before payday (`bill.counted_eur@1`), or `null` for `after_payday`.<br>- `free_until_payday_before`: the hero's "Free until payday" (its first `secondary` Number), with the same `evidence_ref`.<br>- `free_until_payday_after`: `free_until_payday_before - counted` (`bill.free_until_payday_after_eur@1`). It moves exactly by `counted`.<br>- `before`: the hero's `primary`, with the same `evidence_ref`.<br>- `after`: safe to spend recomputed by the hero's own function with `free_until_payday_after` (`bill.safe_to_spend_after_eur@1`). It is the smaller of the balance limit, recomputed, and the monthly budget limit, unchanged, and never below 0.<br>- `text`: one or two sentences.<br><br>The three values of `effect`, for the bill's amount `A` and due date `D`:<br>- `after_payday`: `D` is after `next_payday`. Nothing changes before payday; `reserved`, `counted`, `free_until_payday_after` and `after` are `null`, and `text` says so.<br>- `excess_only`: `D` is on or before `next_payday`, the bill is `matched`, and the matched bill is already among the bills due before payday. Only the excess over what is already counted is added: `counted = max(A - reserved, 0)`.<br>- `full`: `D` is on or before `next_payday`, any other case. `counted = A`.<br><br>When the monthly budget limit is the smaller one, `after` equals `before`, and `text` says why, for example "Your weekly safe to spend stays €138.79: your monthly budget limits it, not your balance." `free_until_payday_after` can be negative: it is shown as it is, and `text` then says that the bill takes more than is free. `after` is never negative: like the hero's, the balance limit counts a negative free until payday as 0, so `after` is then 0. |
| `forecast` | The forecast balance on the bill's due date, before and after the bill (since 0.3.4, #421), or `null` when the balance forecast cannot be computed for a known reason: no transactions, no balance, the bills due of the two paths differ (as `safe_to_spend`), or a failed consistency check of the forecast. The rest of the explanation is unchanged. Fields:<br>- `status`: `covered`; `tight`, when the balance after the bill is below a margin (a server constant, €100); `not_covered`, when it is below zero; or `outside_forecast`, when the due date is before `as_of` or on or after the next payday (the forecast covers today up to the day before payday).<br>- `before`: the balance forecast's own Number for the due date (`balance_forecast.balance_eur@1`), with the same `evidence_ref` as that day of the forecast. For a bill due today it is the balance now (`safe_to_spend.balance_eur@1`).<br>- `already_counted`: what the forecast already subtracts for the matched bill's series by the due date (`balance_forecast.bills_to_date_eur@1` for that series), or `null` when nothing is. This is the part of the forecast's bills up to the due date, not `safe_to_spend.reserved` (up to payday): a monthly bill expected after the due date is not in the balance on the due date yet.<br>- `counted`: what the bill takes from the forecast: the bill's `amount` Number, or, with `already_counted`, only the excess `max(A - already_counted, 0)` (`bill.forecast_counted_eur@1`). So a bill already among the forecast's bills is never subtracted twice.<br>- `after`: `before - counted` (`bill.forecast_after_eur@1`).<br>- `shortfall`: for `not_covered`, `counted - before` (`bill.forecast_shortfall_eur@1`), else `null`.<br>- `text`: one sentence. For `not_covered` it names the shortfall and the date. No text suggests borrowing.<br>- `chip`: for `not_covered`, an `ask` action with the forecast question ("Will my money last until payday?"), else `null`.<br>For `outside_forecast` the Numbers are `null`. The status never removes the payment draft. The due date is taken as printed, with no shift to a banking day, as in `safe_to_spend.effect`. |
| `glossary` | `{term, label, text}`[] for four terms, always all four, in the request language: `reference_number` (viitenumero), `due_date` (eräpäivä), `virtual_barcode` (virtuaaliviivakoodi) and `late_payment_interest` (viivästyskorko). One sentence each; the texts are fixed. The term tokens of #34 are not used here. |
| `actions` | At most two. `add_to_payments` with a payment `draft` `{payee, iban, reference, amount, due_date}`. It is present when `checks.iban` and `checks.reference` are both `pass`. A due date in the past, or any warning sign other than a failed check, does not remove it: paying late is still better than not paying. Then, since 0.3.3 (#420), `open_host_screen` with target `contact_bank` (section 3), the way to a human at the bank, when `signals` holds `iban_check_failed` or `reference_check_failed`, or `new_payee` together with another sign; `new_payee`, `short_term` or `amount_above_usual` alone do not bring it. Pick an action by its `type`, never by its index: with a failed check, `contact_bank` is the only action. With neither, `actions` is empty. The draft's `iban` and `reference` are normalised (no spaces), `amount` is the bill's `amount` Number, and `payee` is `null` for a barcode without one (section 11.3). |
| `warnings` | Sentences the app may show as a small note, as `warnings` are elsewhere in this contract; empty when there is nothing to note. A warning never repeats a signal. Today there is one: a due date in the past, that the payee may charge late-payment interest, without an amount. |
| `signals` | Warning signs, `{code, text, numbers}`[], empty when there are none, in the order of the codes below. This is what the app shows as "warning signs", never as a verdict: no text says that a bill is a fraud. `text` is one plain sentence in the request language, or two for a failed check (what failed and what to do); `numbers` are the Number objects whose `display` it cites, in order (empty when it cites none). The codes:<br>- `iban_check_failed`, `reference_check_failed`: the check digit does not pass (`checks`), for example "This reference number does not pass its check. Compare it with the paper bill before paying."<br>- `new_payee`: the payee matches no regular bill, by label or by known payee name (`match.status` `not_matched` or `no_payee`).<br>- `amount_above_usual`: for a matched bill, the amount is at least 150% of its typical monthly amount; for any other bill, it is above the largest typical monthly amount of the customer's regular bills. Both thresholds are server settings with these defaults.<br>- `short_term`: the due date is fewer than 7 days after `as_of` and not before it (a past due date is in `checks` and `warnings`).<br>Only the two failed checks remove the payment draft; the other signs do not. |

The known payee names of the demo (fictional companies; the sample bills of #249 use the same strings):

| Recurring bill | Its labels (en / fi) | Known payee names |
|---|---|---|
| Housing (`bill_housing_payment`) | Housing / Asuminen | Esimerkki Asunnot Oy |
| Utilities (`bill_utilities_payment`) | Utilities / Kodin laskut | Esimerkki Energia Oy, Esimerkki Vesi Oy |

**Evidence of the computed numbers.** `comparison.change`, `comparison.change_pct`, `safe_to_spend.counted` and `safe_to_spend.free_until_payday_after` open as `composite` (section 9). Their parts are the numbers they are computed from; the bill's amount is a part without an `evidence_ref`. `safe_to_spend.after` opens as a `composite` like the hero's `primary`: the smaller of the two limits, each a part. The budget limit is the hero's own. The balance limit after the bill opens as `metric`: a re-run of `03_safe_to_spend.sql` whose stored settings hold the counted amount (`app.extra_bill_due_eur`, a typed and bounded setting), so it reconciles. `forecast.before` and `forecast.already_counted` open as the balance forecast's own numbers do: `before` as a `composite` of the balance, the bills by that day and the daily pace, and `already_counted` as `transactions`. `forecast.counted` (with `already_counted`), `forecast.after` and `forecast.shortfall` open as `composite`, and the bill's amount is a part without an `evidence_ref` (#421). The `bill.*` methods are defined in the design documents (#242).

**Sentences embed displays.** The texts of `match`, `basket`, `safe_to_spend`, `forecast`, `signals` and `warnings` are fixed server templates that embed the `display` of the numbers they cite, not number tokens (section 2.4): no model writes them.

A matched bill, read from the barcode of section 11.1: the payee is a known payee name of the housing bill. The amount is higher than usual and due before payday, and €780.00 of it is already counted in the bills due before payday, so only the excess of €32.40 is added. It is due tomorrow, so it carries the warning sign `short_term`:

<!-- example: bill.response -->
```json
{
  "customer_id": "CUST00042",
  "as_of": "2026-09-30",
  "language": "en",
  "bill": {
    "source": "barcode",
    "payee": "Esimerkki Asunnot Oy",
    "iban": "FI21 1234 5600 0007 85",
    "reference": "1232",
    "amount": {
      "value": 812.4, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-01", "label": "1 Oct 2026" },
      "method": "bill_barcode@1", "evidence_ref": null,
      "label": "Amount due", "display": "€812.40"
    },
    "due_date": "2026-10-01"
  },
  "checks": { "iban": "pass", "reference": "pass", "due_date": "pass" },
  "match": {
    "status": "matched",
    "bill_id": "bill_housing_payment",
    "label": "Housing",
    "text": "This is your regular Housing bill."
  },
  "comparison": {
    "baseline": {
      "value": 780.0, "unit": "eur_per_month",
      "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "Apr-Sep 2026" },
      "method": "recurring.typical_month_eur@1", "evidence_ref": "ev_h1o3u5s7e9a1",
      "label": "Usual amount", "display": "€780.00 a month"
    },
    "change": {
      "value": 32.4, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-01", "label": "1 Oct 2026" },
      "method": "bill.vs_typical_eur@1", "evidence_ref": "ev_q2w4e6r8t0y2",
      "label": "Difference from the usual amount", "display": "€32.40"
    },
    "change_pct": {
      "value": 4.2, "unit": "percent",
      "period": { "start": "2026-10-01", "end": "2026-10-01", "label": "1 Oct 2026" },
      "method": "bill.vs_typical_pct@1", "evidence_ref": "ev_q3w5e7r9t1y3",
      "label": "Difference from the usual amount", "display": "4.2%"
    },
    "tone": "worse",
    "label": "vs your usual Housing bill"
  },
  "basket": {
    "key": "regular_essentials",
    "label": "Regular essentials",
    "text": "It counts as regular essentials, like your other Housing payments."
  },
  "safe_to_spend": {
    "effect": "excess_only",
    "next_payday": "2026-10-15",
    "reserved": {
      "value": 780.0, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "safe_to_spend.bill_due_eur@1", "evidence_ref": "ev_h5o7u9s1e3a5",
      "label": "Due before payday", "display": "€780.00"
    },
    "counted": {
      "value": 32.4, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "bill.counted_eur@1", "evidence_ref": "ev_k5m7p9r1t3v5",
      "label": "Added to the bills before payday", "display": "€32.40"
    },
    "free_until_payday_before": {
      "value": 395.74, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_s4t6w8y0a2c4",
      "label": "Free until payday", "display": "€395.74"
    },
    "free_until_payday_after": {
      "value": 363.34, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "bill.free_until_payday_after_eur@1", "evidence_ref": "ev_k6m8p0r2t4v6",
      "label": "Free until payday after this bill", "display": "€363.34"
    },
    "before": {
      "value": 184.68, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
      "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_s2t4w6y8a0c2",
      "label": "Safe to spend", "display": "€184.68"
    },
    "after": {
      "value": 169.56, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
      "method": "bill.safe_to_spend_after_eur@1", "evidence_ref": "ev_k7m9p1r3t5v7",
      "label": "Safe to spend after this bill", "display": "€169.56"
    },
    "text": "Due before your payday on 15 Oct. €780.00 is already counted for your Housing bill, so only the extra €32.40 is added: free until payday goes from €395.74 to €363.34, and your weekly safe to spend from €184.68 to €169.56."
  },
  "forecast": {
    "status": "covered",
    "before": {
      "value": 825.63, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-01", "label": "1 Oct 2026" },
      "method": "balance_forecast.balance_eur@1", "evidence_ref": "ev_f2c4a6s8t0b2",
      "label": "Forecast balance on the due date", "display": "€825.63"
    },
    "already_counted": {
      "value": 780.0, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-01", "label": "1 Oct 2026" },
      "method": "balance_forecast.bills_to_date_eur@1", "evidence_ref": "ev_f3h5o7u9s1e3",
      "label": "Already in the forecast for this bill by the due date", "display": "€780.00"
    },
    "counted": {
      "value": 32.4, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-01", "label": "1 Oct 2026" },
      "method": "bill.forecast_counted_eur@1", "evidence_ref": "ev_f4k6m8p0r2t4",
      "label": "Taken from the forecast by this bill", "display": "€32.40"
    },
    "after": {
      "value": 793.23, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-01", "label": "1 Oct 2026" },
      "method": "bill.forecast_after_eur@1", "evidence_ref": "ev_f5k7m9p1r3t5",
      "label": "Forecast balance after this bill", "display": "€793.23"
    },
    "shortfall": null,
    "text": "Your forecast balance on 1 Oct 2026 covers this bill: €793.23 would be left after it.",
    "chip": null
  },
  "glossary": [
    { "term": "reference_number", "label": "Reference number (viitenumero)", "text": "The number that tells the payee which bill a payment is for; its last digit is a check digit, so most typing errors are caught." },
    { "term": "due_date", "label": "Due date (eräpäivä)", "text": "The last day to pay the bill without a late-payment charge." },
    { "term": "virtual_barcode", "label": "Virtual barcode (virtuaaliviivakoodi)", "text": "A 54-digit code that holds the account, amount, reference number and due date, so the bill can be paid without typing them." },
    { "term": "late_payment_interest", "label": "Late-payment interest (viivästyskorko)", "text": "Interest the payee may charge for each day a bill is paid after its due date." }
  ],
  "actions": [
    {
      "type": "add_to_payments",
      "label": "Add to payments",
      "draft": {
        "payee": "Esimerkki Asunnot Oy",
        "iban": "FI2112345600000785",
        "reference": "1232",
        "amount": {
          "value": 812.4, "unit": "eur",
          "period": { "start": "2026-10-01", "end": "2026-10-01", "label": "1 Oct 2026" },
          "method": "bill_barcode@1", "evidence_ref": null,
          "label": "Amount due", "display": "€812.40"
        },
        "due_date": "2026-10-01"
      }
    }
  ],
  "warnings": [],
  "signals": [
    { "code": "short_term", "text": "The due date is less than a week away.", "numbers": [] }
  ]
}
```

The typed bill of section 11.1: the payee matches no regular bill, the reference number fails its check, and the bill is due after payday. There is no payment draft, and there are two warning signs:

<!-- example: bill.response_unknown -->
```json
{
  "customer_id": "CUST00042",
  "as_of": "2026-09-30",
  "language": "en",
  "bill": {
    "source": "fields",
    "payee": "Esimerkki Remontti Oy",
    "iban": "FI71 1234 5600 0098 76",
    "reference": "12345",
    "amount": {
      "value": 145.0, "unit": "eur",
      "period": { "start": "2026-10-20", "end": "2026-10-20", "label": "20 Oct 2026" },
      "method": "user_input@1", "evidence_ref": null,
      "label": "Amount due", "display": "€145.00"
    },
    "due_date": "2026-10-20"
  },
  "checks": { "iban": "pass", "reference": "fail", "due_date": "pass" },
  "match": {
    "status": "not_matched",
    "bill_id": null,
    "label": null,
    "text": "This payee is not one of your regular bills."
  },
  "comparison": null,
  "basket": {
    "key": "unexpected_necessities",
    "label": "Unexpected necessities",
    "text": "It is not one of your regular bills, so it would count as an unexpected necessity. Nothing is saved."
  },
  "safe_to_spend": {
    "effect": "after_payday",
    "next_payday": "2026-10-15",
    "reserved": null,
    "counted": null,
    "free_until_payday_before": {
      "value": 395.74, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_s4t6w8y0a2c4",
      "label": "Free until payday", "display": "€395.74"
    },
    "free_until_payday_after": null,
    "before": {
      "value": 184.68, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
      "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_s2t4w6y8a0c2",
      "label": "Safe to spend", "display": "€184.68"
    },
    "after": null,
    "text": "Due on 20 Oct, after your payday on 15 Oct, so it changes nothing before then."
  },
  "forecast": {
    "status": "outside_forecast",
    "before": null,
    "already_counted": null,
    "counted": null,
    "after": null,
    "shortfall": null,
    "text": "Due on 20 Oct 2026, beyond your balance forecast, which runs until the day before your payday on 15 Oct 2026.",
    "chip": null
  },
  "glossary": [
    { "term": "reference_number", "label": "Reference number (viitenumero)", "text": "The number that tells the payee which bill a payment is for; its last digit is a check digit, so most typing errors are caught." },
    { "term": "due_date", "label": "Due date (eräpäivä)", "text": "The last day to pay the bill without a late-payment charge." },
    { "term": "virtual_barcode", "label": "Virtual barcode (virtuaaliviivakoodi)", "text": "A 54-digit code that holds the account, amount, reference number and due date, so the bill can be paid without typing them." },
    { "term": "late_payment_interest", "label": "Late-payment interest (viivästyskorko)", "text": "Interest the payee may charge for each day a bill is paid after its due date." }
  ],
  "actions": [
    { "type": "open_host_screen", "label": "Contact S-Pankki", "target": "contact_bank" }
  ],
  "warnings": [],
  "signals": [
    { "code": "reference_check_failed", "text": "This reference number does not pass its check. Compare it with the paper bill before paying.", "numbers": [] },
    { "code": "new_payee", "text": "This payee is not one of your regular bills.", "numbers": [] }
  ]
}
```

A bill the forecast does not cover, typed by CUST00849, the persona whose forecast is tightest: €700.00 to an unknown payee, due on 14 Oct, the forecast's lowest day (€641.43). Nothing of it is in the forecast yet, so it takes the whole amount and is €58.57 short: `forecast.status` is `not_covered`, with the `shortfall` and the forecast question as the `chip`. The payment draft stays, and the way to the bank follows it (a new payee with another sign, section 3, `contact_bank`):

<!-- example: bill.response_not_covered -->
```json
{
  "customer_id": "CUST00849",
  "as_of": "2026-09-30",
  "language": "en",
  "bill": {
    "source": "fields",
    "payee": "Esimerkki Remontti Oy",
    "iban": "FI71 1234 5600 0098 76",
    "reference": "12344",
    "amount": {
      "value": 700.0, "unit": "eur",
      "period": { "start": "2026-10-14", "end": "2026-10-14", "label": "14 Oct 2026" },
      "method": "user_input@1", "evidence_ref": null,
      "label": "Amount due", "display": "€700.00"
    },
    "due_date": "2026-10-14"
  },
  "checks": {
    "iban": "pass",
    "reference": "pass",
    "due_date": "pass"
  },
  "match": {
    "status": "not_matched",
    "bill_id": null,
    "label": null,
    "text": "This payee is not one of your regular bills."
  },
  "comparison": null,
  "basket": {
    "key": "unexpected_necessities",
    "label": "Unexpected necessities",
    "text": "It is not one of your regular bills, so it would count as an unexpected necessity. Nothing is saved."
  },
  "safe_to_spend": {
    "effect": "full",
    "next_payday": "2026-10-15",
    "reserved": null,
    "counted": {
      "value": 700.0, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "bill.counted_eur@1", "evidence_ref": "ev_fa842817d5f6",
      "label": "Added to the bills before payday", "display": "€700.00"
    },
    "free_until_payday_before": {
      "value": 819.62, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "safe_to_spend.free_until_payday_eur@1", "evidence_ref": "ev_ef509d0e7ccb",
      "label": "Free until payday", "display": "€819.62"
    },
    "free_until_payday_after": {
      "value": 119.62, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-15", "label": "Until payday on 15 Oct" },
      "method": "bill.free_until_payday_after_eur@1", "evidence_ref": "ev_ee61b33a3f53",
      "label": "Free until payday after this bill", "display": "€119.62"
    },
    "before": {
      "value": 123.15, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
      "method": "safe_to_spend.safe_to_spend_7d_eur@1", "evidence_ref": "ev_b947397749c0",
      "label": "Safe to spend", "display": "€123.15"
    },
    "after": {
      "value": 55.82, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-07", "label": "Next 7 days" },
      "method": "bill.safe_to_spend_after_eur@1", "evidence_ref": "ev_a50e19ad3a3b",
      "label": "Safe to spend after this bill", "display": "€55.82"
    },
    "text": "Due before your payday on 15 Oct 2026, it is added to the bills before payday: free until payday goes from €819.62 to €119.62. Your weekly safe to spend goes from €123.15 to €55.82."
  },
  "forecast": {
    "status": "not_covered",
    "before": {
      "value": 641.43, "unit": "eur",
      "period": { "start": "2026-10-14", "end": "2026-10-14", "label": "14 Oct 2026" },
      "method": "balance_forecast.balance_eur@1", "evidence_ref": "ev_e556874c14c9",
      "label": "Forecast balance on the due date", "display": "€641.43"
    },
    "already_counted": null,
    "counted": {
      "value": 700.0, "unit": "eur",
      "period": { "start": "2026-10-14", "end": "2026-10-14", "label": "14 Oct 2026" },
      "method": "user_input@1", "evidence_ref": null,
      "label": "Amount due", "display": "€700.00"
    },
    "after": {
      "value": -58.57, "unit": "eur",
      "period": { "start": "2026-10-14", "end": "2026-10-14", "label": "14 Oct 2026" },
      "method": "bill.forecast_after_eur@1", "evidence_ref": "ev_c3153e0e6d7c",
      "label": "Forecast balance after this bill", "display": "-€58.57"
    },
    "shortfall": {
      "value": 58.57, "unit": "eur",
      "period": { "start": "2026-10-14", "end": "2026-10-14", "label": "14 Oct 2026" },
      "method": "bill.forecast_shortfall_eur@1", "evidence_ref": "ev_91c833639e58",
      "label": "Short of this bill", "display": "€58.57"
    },
    "chip": {
      "type": "ask",
      "label": "See your balance forecast",
      "prompt": "Will my money last until payday?"
    },
    "text": "Your forecast balance on 14 Oct 2026 does not cover this bill: it is €58.57 short."
  },
  "glossary": [
    {
      "term": "reference_number",
      "label": "Reference number (viitenumero)",
      "text": "The number that tells the payee which bill a payment is for; its last digit is a check digit, so most typing errors are caught."
    },
    {
      "term": "due_date",
      "label": "Due date (eräpäivä)",
      "text": "The last day to pay the bill without a late-payment charge."
    },
    {
      "term": "virtual_barcode",
      "label": "Virtual barcode (virtuaaliviivakoodi)",
      "text": "A 54-digit code that holds the account, amount, reference number and due date, so the bill can be paid without typing them."
    },
    {
      "term": "late_payment_interest",
      "label": "Late-payment interest (viivästyskorko)",
      "text": "Interest the payee may charge for each day a bill is paid after its due date."
    }
  ],
  "actions": [
    {
      "type": "add_to_payments",
      "label": "Add to payments",
      "draft": {
        "payee": "Esimerkki Remontti Oy",
        "iban": "FI7112345600009876",
        "reference": "12344",
        "amount": {
          "value": 700.0, "unit": "eur",
          "period": { "start": "2026-10-14", "end": "2026-10-14", "label": "14 Oct 2026" },
          "method": "user_input@1", "evidence_ref": null,
          "label": "Amount due", "display": "€700.00"
        },
        "due_date": "2026-10-14"
      }
    },
    {
      "type": "open_host_screen",
      "label": "Contact S-Pankki",
      "target": "contact_bank"
    }
  ],
  "warnings": [],
  "signals": [
    {
      "code": "new_payee",
      "text": "This payee is not one of your regular bills.",
      "numbers": []
    },
    {
      "code": "amount_above_usual",
      "text": "This bill is €700.00, more than your largest regular bill (€613.93 a month).",
      "numbers": [
        {
          "value": 700.0, "unit": "eur",
          "period": { "start": "2026-10-14", "end": "2026-10-14", "label": "14 Oct 2026" },
          "method": "user_input@1", "evidence_ref": null,
          "label": "Amount due", "display": "€700.00"
        },
        {
          "value": 613.93, "unit": "eur_per_month",
          "period": { "start": "2026-04-01", "end": "2026-09-30", "label": "1 Apr – 30 Sep 2026" },
          "method": "recurring.typical_month_eur@1", "evidence_ref": "ev_523fbc172441",
          "label": "Usual amount", "display": "€613.93 a month"
        }
      ]
    }
  ]
}
```

### 11.3 The payment draft

**Sentti does not pay.** When the customer taps `add_to_payments`, the app sends the draft to the host app (S-mobiili) in the `sentti.<name>` envelope of the app (PR #175), whose message names are camelCase, like `sentti.openTransaction`. The host shows the payment in its own payment screen, the customer checks and confirms it there, and the host executes it. The service does nothing with the draft and stores nothing; no answer from the host is defined.

| Direction | `type` | `payload` |
|---|---|---|
| module → host | `sentti.paymentDraft` | The action's `draft`: `{payee, iban, reference, amount, due_date}`. `amount` is a Number object (section 2.1), so the host shows the same `display` the customer saw. `payee` can be `null`; the host then asks for it. |
| module → host | `sentti.openHostScreen` | `{target}` and nothing else, `target` being `monthly_saving`, `bonus_to_fund` or `contact_bank` (since 0.3.3): from the action `open_host_screen` (since 0.3.1; section 3, Actions; example `host.open_host_screen`). The host opens its own screen for the target and ignores a target it does not know. |

<!-- example: host.payment_draft -->
```json
{
  "type": "sentti.paymentDraft",
  "v": 1,
  "payload": {
    "payee": "Esimerkki Asunnot Oy",
    "iban": "FI2112345600000785",
    "reference": "1232",
    "amount": {
      "value": 812.4, "unit": "eur",
      "period": { "start": "2026-10-01", "end": "2026-10-01", "label": "1 Oct 2026" },
      "method": "bill_barcode@1", "evidence_ref": null,
      "label": "Amount due", "display": "€812.40"
    },
    "due_date": "2026-10-01"
  }
}
```

### 11.4 Reading a sample bill (not implemented yet)

**Not implemented yet** (#249, #250). The two endpoints below are decided but not built, and this subsection stays marked until they are on the dev environment. The demo reads only the sample bills of a gallery; a visitor's own file is not sent anywhere.

**`GET /api/bill/samples?lang=en`** lists the sample bills: `{samples: [{sample_id, title, language, image_url}]}`. `language` is the bill's own language, and `image_url` is a static image. The true fields of a sample are never in this response.

**`POST /api/bill/read`** with `{customer_id, language, sample_id}` reads one sample bill: a language model reads the image, and code checks what it read. The response is a proposal, not an explanation: `{sample_id, language, fields, needs_confirmation}`, where `language` is the request's language (the bill's own language is in the samples list).
- `fields` has the keys `payee`, `iban`, `reference`, `amount`, `due_date` and `barcode`. Each is `{value, display, status, source, note}`, or `null` when it was not found or failed its format check (it is dropped, never repaired):
  - `value`: the normalised string, for example `"FI2112345600000785"` or `"812.40"`; `display`: the same, formatted for display.
  - `status`: `checked` or `unchecked`. `checked` means code checked it: a barcode that parses, the fields taken from that barcode, or an IBAN or reference that passes its check digit. Without a barcode, `amount`, `due_date` and `payee` are always `unchecked`.
  - `source`: `barcode` or `printed`.
  - `note`: a sentence or `null`, for example when the amount in the barcode and the printed amount differ.
- `needs_confirmation` is always `true`. A reading contains no Number objects.

The user then confirms or corrects every field. The app sends the confirmed `barcode`, or the confirmed fields as `fields`, to `POST /api/bill/explain` (section 11.1), where the methods are `bill_barcode@1` and `user_input@1`. **Unconfirmed fields never reach an answer.**

When the model may not be used (switched off, out of budget, paused, an error, or an answer that does not fit the schema), the reading is 503 `model_unavailable`, with no retry; the app then offers typing the fields.

A reading of a sample with a barcode (not implemented yet):

<!-- example: bill.read_response -->
```json
{
  "sample_id": "sample_2",
  "language": "fi",
  "fields": {
    "payee": { "value": "Esimerkki Asunnot Oy", "display": "Esimerkki Asunnot Oy", "status": "unchecked", "source": "printed", "note": null },
    "iban": { "value": "FI2112345600000785", "display": "FI21 1234 5600 0007 85", "status": "checked", "source": "barcode", "note": null },
    "reference": { "value": "1232", "display": "1232", "status": "checked", "source": "barcode", "note": null },
    "amount": { "value": "812.40", "display": "812,40 €", "status": "checked", "source": "barcode", "note": null },
    "due_date": { "value": "2026-10-01", "display": "1.10.2026", "status": "checked", "source": "barcode", "note": null },
    "barcode": { "value": "421123456000007850008124000000000000000000001232261001", "display": "421123456000007850008124000000000000000000001232261001", "status": "checked", "source": "barcode", "note": null }
  },
  "needs_confirmation": true
}
```

---

## 12. Changelog

| Version | Change |
|---|---|
| 0.1.0 | First draft: five endpoints, Number object, cards, streaming events (issue #5). |
| 0.1.1 | Review fixes:<br>- `/api/ask` validation errors (400, 404, 429) arrive as HTTP errors before the stream; the stream's `error` event uses the `{"error": …}` envelope.<br>- New `done.clarify` and a `warnings` code list.<br>- New `card.whatif` example; `estimate` and `evidence_ref` sit on the card, not in `result`.<br>- Breakdown key `other` documented.<br>- Conversations are bound to one customer.<br>- Evidence kind `input` removed.<br>- `ai_disclosure` uses the agreed default text.<br><br>Aligned with `metrics.md` (#6):<br>- Age bands and profile keys, traits and features as enums.<br>- Peer `level` replaces `widened`; peers need at least 20 others.<br>- Safe to spend covers the 7 days after today, with components and two limits.<br>- Bills carry the metrics `status`, with Utilities as one `spread` bill.<br>- What-if takes `{selection, cut_pct}` and returns a `status`, savings per month, week and year, and the excluded one-offs and regular essentials; `horizon`, `projected_per_month` and the cancel and switch scenarios are removed.<br>- `stores` carries confidence intervals and a `switch.status`, with no saving unless the status is `estimate`.<br>- Baskets show monthly averages over the window.<br>- Method ids are `<metric>.<output column>@<version>`, using the metrics output names. |
| 0.1.2 | Example values follow the safe-to-spend formula (#32).<br><br>New field:<br>- `metric.status` (`ok`, `below_usual`, `nothing_free` or `null`); the hero example carries `"status": "ok"`.<br><br>New method id:<br>- `safe_to_spend.bill_due_eur@1` for each bill's `due_until_payday` (pending as a SQL output column, issue #44); the bills total keeps `safe_to_spend.bills_due_eur@1`.<br><br>Changed example values in `overview.response`:<br>- essentials reserve 147.00 → 134.76;<br>- irregular reserve 61.50 → 167.46;<br>- free until payday 489.46 → 395.74;<br>- balance limit 228.41 → 184.68;<br>- budget limit 292.24 → 248.50;<br>- safe to spend 228.41 → 184.68;<br>- regular essentials 1,180.20 → 1,180.21 a month;<br>- total spending 2,211.00 → 2,211.01 a month.<br><br>`ask.json.response_fi` gains `"status": null` on its metric card. |
| 0.2.0 | The coach asks about a spending spike (#33).<br><br>New:<br>- Card type `review`: one spike, an opaque `tx_ref`, a merchant alias with no id, the question in English and Finnish, and exactly two options, `unexpected_necessities` ("needed") and `everyday_spending` ("I chose it").<br>- Basket state `unclassified` ("Waiting for your answer"): while a review is pending, the purchase is in no basket and not in the reserve. "Needed" lowers safe to spend, "I chose it" leaves it unchanged, and no answer raises it.<br>- Endpoint `POST /api/baskets/label` (section 10):<br>&nbsp;&nbsp;- idempotent; `changes` is empty when nothing changed;<br>&nbsp;&nbsp;- undo with `basket: null`, which returns the purchase to `unclassified` while the review is open;<br>&nbsp;&nbsp;- `review_state`, and `message` with number tokens;<br>&nbsp;&nbsp;- errors `tx_ref_not_found` (also for another customer's ref, R4) and `basket_not_allowed`, and 400 for a value that is not a basket key.<br>- Overview fields:<br>&nbsp;&nbsp;- `reviews`: at most one pending review; at most 3 created per calendar week; never the same transaction twice; never Health.<br>&nbsp;&nbsp;- `safe_to_save`: a new card type. The headline is `monthly`; the second line is `stock` with `stock_explanation` and no call to action. When `monthly` is 0, a `reason` follows the sign of free month: `essentials_exceed_income` or `largest_everyday_category`. No component amount is negative. Its method ids are pending as SQL outputs (#53).<br>- `/api/ask` may carry the pending `review` card, added by the server.<br>- A timestamp convention (section 1).<br><br>Changed:<br>- `GET /api/overview` now has one idempotent side effect: its first serve creates the pending review. It stays safe to call on every app open.<br>- The changelog moved from section 10 to section 11, so its anchor is `#11-changelog`.<br>- The `invalid_scenario` row of the errors table is reworded: the cancel scenario it mentioned no longer exists.<br><br>New examples, all with dataset values except CUST00042:<br>- `overview.response_pending` and `card.review` (Sanna, review pending);<br>- `card.safe_to_save` (Sanna after "needed"), `card.safe_to_save_aleksi`, `card.safe_to_save_zero` (CUST00002) and `card.safe_to_save_everyday` (CUST00019);<br>- the label examples: "needed", "I chose it", undo and error;<br>- `overview.response` (CUST00042, illustrative) gains `safe_to_save` and an empty `reviews`. |
| 0.2.1 | No change of shape. The method ids `safe_to_spend.bill_due_eur@1` (#44) and `safe_to_spend.safe_to_save_monthly_eur@1`, `.everyday_month_eur@1`, `.safe_to_save_eur@1`, `.everyday_until_payday_eur@1`, `.essentials_shortfall_month_eur@1`, `.save_reason_month_eur@1` (#53) are real SQL outputs now; the pending notes are removed. The bills card states that its items, each rounded on its own, may differ from `total` by up to 0.01 per item. |
| 0.2.2 | Documents what the service already returns or what was decided (#134); nothing new is built.<br><br>1. Evidence rows carry `display`, the amount formatted like a Number's display; `amount` stays the exact decimal string (section 9; #106).<br>2. Evidence kinds: `metric` (a re-run of the metric definition, `reconciles`, `rows` always a list) and the shape of `peer_aggregate` (group statistics as parts with `evidence_ref: null`, the level in the group size's label); new examples `evidence.response_metric` and `evidence.response_peer` (sections 2.1 and 9; #73, #106, #95).<br>3. Errors: `not_found` (404) for an unknown route; a wrong method is 405 `invalid_request` with `Allow` (section 4; #106).<br>4. `POST /api/whatif`: every refused selection answers 422 `invalid_scenario` with the same body; `language` defaults to `en`; `cut_pct` is a JSON integer; a merchant alias is accepted and the merchant id echoed; `unexpected_necessities` is allowed; new example `whatif.error` (section 8.1; #106).<br>5. Only the persona customers are served; any other id answers 404 `customer_not_found` (sections 1, 4, 5 and 9; #125).<br>6. `hero` is `null` when safe to spend cannot be computed for a known reason; the app hides the card (section 6; #106).<br>7. The hero subtitle shows the period's dates, "1–7 Oct 2026" / "1.–7.10.2026" (section 6; #113, #133).<br>8. The display rules of the one formatter (section 2.1; #111).<br>9. The review card texts as decided on #68: the question with the amount, category and date filled in, the buttons "Needed" / "My choice" ("Välttämätön" / "Oma valinta"), and the Finnish effect texts with "turvallisesti käytettävissä" (sections 3 and 6).<br><br>Also: error messages follow `?lang` for a GET, the body's `language` for a POST, and the detected language for `/api/ask` with `auto`. A POST body that cannot be read or does not validate is answered in the language of the `lang` query parameter, else in English, and on `/api/ask` in English (sections 1, 4, 7.1, 8.1 and 10.1).<br><br>Facts added after the first draft:<br>10. The first overview creates the review (with #196, also the first `/api/ask` answer); an undo after the 7 days closes it (section 6, as in 10.1).<br>11. With #144 (PR #199): the per-viewer cookie `sentti_viewer` set by the overview, and a rate limit on the label write, answered with 429 `rate_limited` and `Retry-After` (sections 6 and 10).<br>12. `safe_to_save`: when free until payday is negative, `stock` is 0 and `stock_components` is empty (section 3; #165).<br>13. The reason text of `card.safe_to_save_everyday` names the category in a form that works for every everyday category (#165).<br>14. The "My choice" button's text in sections 10.1 and 10.2; the `metric` rows are always a list; the `peer_aggregate` shape as #69 builds it; which hero number opens as which evidence kind (section 9).<br>15. New example `overview.response_no_hero`: the overview when safe to spend cannot be computed (section 6). |
| 0.3.0 | The bill explanation (#243; built in #242).<br><br>New:<br>- Section 11, `POST /api/bill/explain`: a bill as a virtual barcode or as typed fields. The response carries `bill`, `checks`, `match`, `comparison`, `basket`, `safe_to_spend`, `glossary`, `actions`, `warnings` and `signals`. Examples `bill.request`, `bill.request_fields`, `bill.response`, `bill.response_unknown` and `bill.error`.<br>- The payee is matched exactly against the recurring bills' labels and a fixed table of fictional payee names, which stands in for the counterparty history a real bank has.<br>- `safe_to_spend`: the bill is applied to the balance side like a bill due before payday, and the hero's own computation runs again: `free_until_payday` and safe to spend, each before and after.<br>- `signals`: warning signs with the codes `iban_check_failed`, `reference_check_failed`, `new_payee`, `amount_above_usual` and `short_term`, never a verdict (#242, decision 10).<br>- The action `add_to_payments` and the host message `sentti.paymentDraft` (section 11.3, example `host.payment_draft`): the host shows, confirms and executes the payment; Sentti does not pay.<br>- Section 11.4, decided and not implemented yet: `GET /api/bill/samples` and `POST /api/bill/read` with `sample_id`; a reading is a proposal of fields marked `checked` or `unchecked` that the user confirms (#249, #250; example `bill.read_response`).<br>- Section 1: a bill reading is the third exception of the Number rule; its fields are strings.<br>- Error codes 422 `invalid_bill`, whose body adds `reason`, and, with the reading, 503 `model_unavailable` (section 4).<br>- Method `bill_barcode@1`, a value read from a bill's virtual barcode, with no evidence ref (sections 2.1 and 9), and the `bill.*` methods of the numbers the bill explanation computes, whose composite evidence has a bill part without a ref.<br><br>The changelog is now section 12. |
| 0.3.1 | After 0.3.0. One step from a card into the host app's own screens (#267).<br><br>New:<br>- Action `open_host_screen` with `label` and `target` from the closed list `monthly_saving` and `bonus_to_fund` (section 3, Actions; example `action.open_host_screen`).<br>- The `safe_to_save` card carries it with `monthly_saving` when `monthly` is above 0. The S-Bonus estimate's `metric` card carries it with `bonus_to_fund` when the estimate is offered.<br>- Host message `sentti.openHostScreen` with the payload `{target}` and nothing else (example `host.open_host_screen`; a row in the host-message table of section 11.3; `docs/integration.md` section 3). The host opens its own screen and ignores a target it does not know. The envelope is the app's, from PR #175.<br><br>Changed examples: the safe-to-save cards whose `monthly` is above 0 carry the new action, in `card.safe_to_save`, `card.safe_to_save_aleksi`, `overview.response`, `overview.response_pending` and `overview.response_no_hero`. `card.safe_to_save_zero` and `card.safe_to_save_everyday` (`monthly` 0) do not. |
| 0.3.2 | The effect of an answer to a review card (#382). New: `effect` in the response of section 10 (`POST /api/baskets/label`), `{items, text, text_rendered, numbers}` or `null`: the headline numbers before and after (safe to spend, safe to save, the reserve, the basket the purchase moved into), exactly as the overview shows them, and the effect text built from their real difference. `message` now carries the same text, never a fixed promise. An undo returns the sides swapped. Examples `label.response`, `label.response_wanted` and `label.response_undo` gain `effect`. |
| 0.3.3 | The way to a human and the AI disclosure (#420).<br><br>New:<br>- Target `contact_bank` in the closed list of `open_host_screen` (section 3), label "Contact S-Pankki" / "Ota yhteyttä S-Pankkiin"; the host message `sentti.openHostScreen` carries it as `{target}` only.<br>- `done.actions` (Action[]): every refusal, the "I can't answer that one yet" answer and the "nothing found" fallback carry the `contact_bank` action; other answers `[]`.<br>- `done.ai_disclosure` (string or null): the overview's disclosure text on the first answer of a conversation unless it is the introduction; `null` afterwards.<br>- The bill explanation's `actions` holds at most two: the payment draft, then `contact_bank` with a failed check or an unknown payee together with another sign.<br><br>Examples `ask.sse.done`, `ask.json.response_fi`, `ask.json.response_refusal`, `ask.json.response_clarify` and `bill.response_unknown` gain the fields; new pair `ask.json.request_refusal_first` / `ask.json.response_refusal_first`. No refusal text changes. |
| 0.3.4 | After 0.3.3. The forecast balance on a bill's due date (#421).<br><br>New:<br>- `forecast` in the response of section 11 (`POST /api/bill/explain`): `{status, before, already_counted, counted, after, shortfall, text, chip}`, or `null`. It is `null` when the balance forecast cannot be computed: no transactions, no balance, the bills due of the two paths differ, or a failed consistency check of the forecast; the rest of the explanation is unchanged. `status` is one of `covered`, `tight` (below a server constant, €100), `not_covered` and `outside_forecast`. `before` is the balance forecast's own Number for the due date. A bill already among the forecast's bills takes only its excess over what the forecast subtracts for it by the due date. `chip` is an `ask` action with the forecast question, for `not_covered` only. The status never removes the payment draft.<br>- Methods `bill.forecast_counted_eur@1`, `bill.forecast_after_eur@1` and `bill.forecast_shortfall_eur@1`, which open as `composite`.<br><br>Changed examples: `bill.response` (`covered`, with €780.00 already in the forecast for the housing bill on 1 Oct) and `bill.response_unknown` (`outside_forecast`, due after payday). New example `bill.response_not_covered` (CUST00849, €700.00 due on 14 Oct: €58.57 short, with the `shortfall` and the `chip`). |
