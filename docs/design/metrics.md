# Money metrics: definitions and SQL prototypes

Issue #6. Every number the coach says comes from one of these deterministic definitions; the LLM only explains them (rules R1 and R2 of the research in #3, `docs/design/research-bank-assistants.md`). This document fixes the formulas, edge cases and output columns. Tool names and JSON shapes belong to #5; the columns listed here are what those tools map.

Prototypes: `core/metrics/01_recurring.sql` … `07_store_price_index.sql`. Each file runs on its own.

| # | Metric | Partner question it answers | File |
|---|---|---|---|
| 1 | Three baskets | Where did my money go? | `02_baskets.sql` |
| 2 | Recurring bills and income cadence | Where did my money go? (and input to 3) | `01_recurring.sql` |
| 3 | Safe to spend this week | What can I safely spend this week? | `03_safe_to_spend.sql` |
| 4 | What-if savings | How could I save more? | `04_what_if.sql` |
| 5 | Spender profile | What kind of spender am I? | `05_spender_profile.sql` |
| 6 | Peer benchmark | What kind of spender am I? | `06_peer_benchmark.sql` |
| 7 | Store price index and switch saving | How could I save more? | `07_store_price_index.sql` |
| 11 | Down payment plan (optional, after the MVP) | How could I save more? | definition only |

## 0. Conventions shared by all metrics

**Inputs.** Each file reads session settings and falls back to defaults, so it also runs with no settings at all:

```sql
SET app.demo_today    = '2026-09-30';  -- "today"; default 2026-09-30
SET app.customer_from = 'CUST00001';   -- inclusive; default CUST00000
SET app.customer_to   = 'CUST00002';   -- exclusive; default CUST00100 (the 99-customer sample)
\i core/metrics/03_safe_to_spend.sql
```

For one customer, set the range to `[id, next id)`. Metrics 1 to 5 depend only on the customer's own rows, so a one-customer run returns the same numbers as the sample run. Metrics 6 and 7 compare with the whole population when the marts of section 8 are built for that "today", and otherwise with the customers in the range (see their sections).

**Time (R5).** No statement reads a transaction with `tx_date > DEMO_TODAY`. The bound sits directly in every `WHERE` on `transactions`.

**Window.** Averages use the **last 6 complete calendar months**: a month counts if its last day is on or before today. For today = 2026-09-30 that is 2026-04-01 … 2026-09-30; for today = 2026-09-14 it is 2026-03-01 … 2026-08-31. A "month average" is the window total divided by `n_months`, the number of window months the customer has history in (1 to 6; it is 6 for every sample customer). Daily rates divide by the window's days (183 for Apr–Sep).

**Units.** Spend is positive euros (`out_eur = -amount_eur`), rounded to 2 decimals at the end only. Percentages have 1 decimal. Ties in "last" rows break on `tx_at DESC, id DESC`. Every output has `period_start` and `period_end` (the `period` of the number object).

**Flows.** Category decides what a transaction is; `tx_type` (the bank's "economic purpose") maps 1:1 to category in this data and is used for bills:

| Flow | Categories | Counts as spending? |
|---|---|---|
| income | Salary, Other Income, Invest Withdraw | no |
| saving | Invest Deposit | no (shown as saving) |
| transfer | Salary Sweep | no (see 2.3) |
| spend | all other categories | yes |

**One-off (spike).** A purchase is a one-off if it is more than **5×** the customer's median purchase in the same category over the 365 days up to today, and the customer has at least 8 purchases in that category in those 365 days. One-offs stay in their basket totals but are excluded from "typical" baselines (what-if, everyday run-rate). On the sample (all 2 years, today 2026-09-30), 1,033 of 57,017 purchases are one-offs: Restaurants 585, Entertainment 224, Health 89, Lifestyle 59, Home & Tech 42, Travel 17, Transportation 11, Groceries 6.

**Evidence (R2).** Each section lists the filter that returns the rows a number was computed from. Summing `out_eur` over those rows reproduces the value. Derived numbers (safe to spend) list their input numbers instead.

**Facts about the data this design relies on** (checked on the sample `customer_id < 'CUST00100'`, 99 customers, 68,917 rows, 2024-10-01 … 2026-09-30):
- One account per customer. `balance_after` is a consistent running balance: 0 mismatches in 68,818 consecutive pairs.
- No refunds: every purchase is negative, every income positive.
- Empty merchant or MCC is stored as NULL, never "." (no "." values in the sample). 3,072 purchases (5.4%) have no merchant and no MCC (non-card payments); rules fall back to category for them.
- Salary arrives once a month, on the 15th in 80% of months and on the 26th–31st in 20% ("late").
- **Salary Sweep is monthly, not yearly**: 5 of 99 customers have it every month, the day after salary, about 90% of the salary. Those customers have no Housing and spend little from this account.
- Housing is once a month at a stable amount (median CV 3%), but some customers miss months (CUST00002 paid none in Aug and Sep 2026).
- Utilities come about 3 times a month at varying amounts (median CV of the monthly total 31%).
- No card merchant charges a customer once a month at a stable amount, so "subscriptions" are empty in this data; recurrence comes from bill and income types.

## 1. Three baskets — "Where did my money go?"

Keys (shared with #5) and labels from the partner brief:

| Key | Label | Meaning |
|---|---|---|
| `regular_essentials` | Regular essentials | Needed and predictable: bills, groceries, commuting |
| `unexpected_necessities` | Unexpected necessities | Needed but lumpy: health, home and tech, one-off essential purchases |
| `everyday_spending` | Everyday spending | Discretionary, frequent: eating out, entertainment, shopping, travel, taxis |

**Rules** (spend flow only; first match wins, after user overrides):

| # | Condition | Basket |
|---|---|---|
| 1 | `tx_type` is `housing_payment` or `utilities_payment` | regular_essentials |
| 2 | card merchant detected as a monthly subscription (section 2) | regular_essentials |
| 3 | category Health or Home & Tech (any MCC, also NULL) | unexpected_necessities |
| 4 | Transportation with MCC 4121 (taxi) | everyday_spending |
| 5 | Groceries or Transportation and a one-off | unexpected_necessities |
| 6 | Groceries or Transportation (public transport 4111, fuel 5541/5542, parking 7523, NULL) | regular_essentials |
| 7 | Restaurants, Entertainment, Lifestyle, Travel | everyday_spending |
| 8 | anything else (a new category) | `unclassified` |

Health is only ever summed into `unexpected_necessities` or shown as a category amount when the user asks; it never drives a label or statement about the person (R9).

**User overrides.** A user can move a merchant, an MCC or a whole category to another basket. Most specific wins: merchant > MCC > category. Product table (not created by this issue):

```sql
CREATE TABLE basket_overrides (
    customer_id text NOT NULL,
    merchant_id text, mcc text, category text,      -- exactly one is set
    basket      text NOT NULL CHECK (basket IN ('regular_essentials','unexpected_necessities','everyday_spending')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(merchant_id, mcc, category) = 1)
);
```

In the prototypes the same shape is an empty `overrides` CTE, joined by `LEFT JOIN LATERAL … ORDER BY specificity LIMIT 1`; the per-transaction flag `overridden` lives in the `cls` CTE (the evidence query for a basket returns it). Tested with two rows for CUST00001 (category Travel → unexpected_necessities, MCC 7922 → regular_essentials): everyday spending fell from 399.99 to 328.82 a month, unexpected necessities rose from 409.17 to 466.65 and regular essentials from 1,278.77 to 1,292.46; the total stayed the same.

**Output** (`02_baskets.sql`, one row per customer and basket): `month_avg_eur`, `month_avg_excl_one_off_eur`, `one_off_total_eur`, `n_one_off`, `share_pct` (of the customer's spend), `total_eur`, `n_tx`, `n_months`, `period_start`, `period_end`.

**Evidence.** Transactions of the customer with flow spend, `tx_date` in the window, and the basket after the rules above. `sum(out_eur) = total_eur`.

**Edge cases.** No spending in a basket: no row (the API shows 0). Customer with under 6 months of history: `n_months` < 6 and averages divide by it. Category not in the table: `unclassified`, never silently dropped.

**Worked numbers** (window 2026-04-01 … 2026-09-30, month averages):

| Customer | Regular essentials | Unexpected necessities | Everyday spending |
|---|---|---|---|
| CUST00001 | 1,278.77 (61.2%) | 409.17 (19.6%) | 399.99 (19.2%) |
| CUST00002 | 1,129.45 (66.4%) | 142.42 (8.4%); 126.89 without one 93.17 one-off | 430.29 (25.3%); 383.09 without one 283.24 one-off |
| CUST00006 | 169.32 (66.8%) | 34.23 (13.5%) | 49.99 (19.7%) |

### 1.1 Customer labels for spending spikes (#33)

The coach asks about a spike: was it needed, or everyday spending the customer chose? The answer becomes a **label on that one transaction**. The person decides what their own spending means.

**Three states of an asked spike** (design doc, section 7.8, has the state machine):
- **Pending** (review open, not answered): the purchase is `unclassified`, "Waiting for your answer". It is in **no basket total** and **not in the reserve for unexpected necessities**. As a one-off it stays out of the everyday run rate, as before.
- **Answered "needed"** (`unexpected_necessities`): the purchase is in that basket and in its reserve.
- **Answered "I chose it"** (`everyday_spending`): the purchase is in that basket. As a one-off it stays out of the everyday run rate.

A spike that was never asked about, or whose review closed unanswered, keeps the basket the rules give it. So every number of a customer without a pending review is exactly as before, including the worked numbers of this document, the personas' reference values and the eval set.

**Precedence.** A label is the most specific override: transaction label (or `unclassified` while pending), then merchant, then MCC, then category, then the rules above. In SQL it is one more level in the shared classification block:
- the `overrides` CTE gets a `tx_id` column;
- the lateral join matches `o.tx_id = x.id` first;
- `ORDER BY` puts `(o.tx_id IS NOT NULL) DESC` first.

The product table is `spike_reviews` (design doc, section 7.8). Its answered rows are read as transaction-level overrides to their basket, and its pending rows as overrides to `unclassified`.

**What can be labelled.** The two target baskets are `unexpected_necessities` and `everyday_spending` only. The transaction must be:
- a purchase in the spend flow, inside the window;
- a one-off by the spike rule of section 0;
- in `unexpected_necessities` or `everyday_spending` by the rules above.

It is never a Health purchase or a health MCC (5912, 8011, 8099, 8021). Those spikes are never asked about and stay in `unexpected_necessities` silently (R9).

**What a label changes.**
- **The basket only.** The purchase stays a one-off, because the spike rule depends on amounts, not baskets. Baselines that leave one-offs out therefore do not move: usual everyday spending (section 3) and the what-if baseline (section 4).
- **Downstream:**
  - basket totals and shares (`02`);
  - the irregular reserve and with it free until payday, the budget limit and safe to spend (`03`, and safe to save in 3.1);
  - basket shares in the profile (`05`); the everyday share can cross 30%, and the label then changes only if no earlier rule matches;
  - the basket metrics of the peer benchmark (`06`).
- **Marts:** the precomputed marts of section 8 must be refreshed for that customer.
- **Undo:** an undone label returns the purchase to `unclassified` while the review is open, and to the rules after that.

**Effects of the answers** (product decision, recorded on issue #33). The formulas do not change; only the starting state of a spike with a pending review does.
- **Pending:** the purchase is outside the reserve, so safe to spend is the same as after "I chose it".
- **"Needed":** the purchase joins the reserve for unexpected necessities, so the reserve grows and **safe to spend goes down**. The coach explains that it keeps a reserve for surprises like this. This is the demo path; the bank's own example is a washing machine.
- **"I chose it":** the purchase joins everyday spending, and **safe to spend does not change**. The coach says this month's everyday spending is higher than usual by the amount.
- **No answer raises safe to spend above the value shown while the question was pending.** Undo and changing the answer only move between these states. A review that expired unanswered cannot be answered any more (its `tx_ref` is no longer valid), so the purchase stays in its rule-based basket.

**Worked numbers.** CUST00860 (persona Sanna), transaction 606016: Home & Tech, 1,080.42 on 2026-09-28. It is 9.0 times her median Home & Tech purchase and a one-off, so the rules put it in `unexpected_necessities`. Window 2026-04-01 … 2026-09-30 (183 days); payday 2026-10-15, N = 15. The first column is both "no review" and "after 'needed'"; the two states give the same numbers.

| | No review = after "needed" | Review pending (`unclassified`) | After "I chose it" |
|---|---|---|---|
| Unexpected necessities, window total | 3,126.90 | 2,046.48 | 2,046.48 |
| Everyday spending, window total | 3,602.44 | 3,602.44 | 4,682.86 |
| Unclassified, window total | – | 1,080.42 | – |
| Regular essentials, window total | 11,334.21 | 11,334.21 | 11,334.21 |
| Month averages (regular / unexpected / everyday / unclassified) | 1,889.04 / 521.15 / 600.41 / – | 1,889.04 / 341.08 / 600.41 / 180.07 | 1,889.04 / 341.08 / 780.48 / – |
| Shares | 62.7% / 17.3% / 19.9% | 62.7% / 11.3% / 19.9% / 6.0% | 62.7% / 11.3% / 25.9% |
| Irregular reserve (15 days) | 256.30 | 167.74 | 167.74 |
| Free until payday | 12,567.56 | 12,656.12 | 12,656.12 |
| Irregular spending per month (budget limit input) | 520.08 | 340.38 | 340.38 |
| Budget limit 7d | 180.26 | 221.58 | 221.58 |
| **Safe to spend 7d** (binding: budget) | **180.26** | **221.58** | **221.58** |
| Usual everyday spending per 7 days | 137.80 | 137.80 | 137.80 (the purchase is still a one-off) |
| Safe to save (3.1) | 12,272.28 | 12,360.83 | 12,360.83 |
| Safe to save monthly (3.1) | 184.61 | 364.31 | 364.31 |

From pending, "needed" moves 1,080.42 into unexpected necessities and grows the reserve by 1,080.42 / 183 × 15 = 88.56. Irregular spending per month rises by 1,080.42 / 183 × 30.4375 = 179.70, so the budget limit and safe to spend fall from 221.58 to 180.26. "I chose it" moves 1,080.42 into everyday spending and changes no limit. Both basket totals move by exactly the labelled amount. Shares are rounded on their own, so a column may add up to 99.9%.

**How the columns were computed.**
- `02_baskets.sql` and `03_safe_to_spend.sql` were run for the range `CUST00860` … `CUST00861`:
  - once as committed (no review);
  - once with the transaction-level override described above set to `unclassified` (pending);
  - once with it set to `everyday_spending` ("I chose it").
- All runs used one read-only connection with `statement_timeout = '60s'`.
- The override change is the specification for the SQL. It is not committed yet, because implementing labels is a separate issue.
- Safe to save was computed in the same runs with the formula of 3.1.

## 2. Recurring bills and income cadence

**Series.** A non-card flow is keyed by `tx_type` (salary, housing_payment, utilities_payment, investment_deposit, salary_sweep, …). A card purchase is keyed by `merchant_id`.

**Recurring** if, in the 6-month window:
- the series appears in at least **4 of the 6** months; and
- for a merchant series, it is charged **exactly once** in each month it appears, with a monthly amount CV ≤ 0.10 (subscription-like). Bill and income types qualify on presence alone, because their amounts can vary (Utilities CV up to 0.47).

Cadence is monthly; no weekly or yearly series exists in this data (the yearly April sweep in the issue text does not appear in the sample).

**Per series:**
- `typical_month_eur`: median of the monthly totals of the months it appears in.
- `tx_per_month`: median count per month. If above 1 (Utilities), the series is `spread` and has no single due date.
- `typical_day`: lower median of the day of the month's first payment.
- `status` and `next_expected_date`:

| Situation | status | next_expected_date |
|---|---|---|
| several payments a month | `spread` | none (use pro rata) |
| already paid this month | `done_this_month` | typical day next month (clamped to month end) |
| not paid, today on or before the typical day | `upcoming` | typical day this month; tomorrow if today is the typical day |
| income not paid, after the typical day | `late` | last day of this month (or tomorrow if today is the last day) |
| bill not paid, 1 to 7 days after the typical day | `late` | tomorrow |
| bill not paid, more than 7 days after | `skipped_this_month` | typical day next month |

The typical day is compared as a date clamped to the month's end (day 31 in a 30-day month is the 30th). All of today's transactions are in the data, so a payment missing on its typical day is still `upcoming` and expected tomorrow; it becomes `late` the day after. Example: CUST00001 on 2026-05-15 (that month's salary came on the 29th): `upcoming`, expected 2026-05-16.

- `late_share_12m` (salary): share of the last 12 months whose salary came on day 26 or later.

**Output** (`01_recurring.sql`, one row per recurring series): `series_kind`, `series_key`, `direction` (in or out), `cadence`, `months_present`, `tx_per_month`, `typical_month_eur`, `cv_month`, `typical_day`, `last_date`, `last_amount_eur`, `last_tx_id`, `n_tx_this_month`, `paid_this_month_eur`, `status`, `next_expected_date`, `late_share_12m`, `period_start`, `period_end`.

**Evidence.** The series' transactions in the window (for typical amounts) plus `last_tx_id`.

### 2.3 Salary Sweep and "sweep customers"
A sweep is a **transfer**, not spending and not saving. It reduces the money available on this account (safe to spend uses income minus sweep), and it is never reserved as a bill before payday, because it follows the salary.

**Sweep customer** has one definition everywhere: a Salary Sweep in **at least 4 of the 6 window months**, which is exactly a recurring `salary_sweep` series. It is used in three places: 03 nets the sweep series out of income; 05 gives the trait `salary_moved_elsewhere`; 06 leaves the customer out of every peer group. Open question 1 (what a sweep really is) is with the bank's people.

**Income** means Salary + Other Income in every metric. Invest Withdraw is the customer's own saving coming back, so it is not income.

**Worked numbers** (today 2026-09-30):

| Customer | Series | Typical / month | Day | Status | Next expected |
|---|---|---|---|---|---|
| CUST00001 | salary (in) | 2,364.88 | 15 | done_this_month; late in 25% of the last 12 months | 2026-10-15 |
| | housing_payment | 528.38 | 4 | done_this_month | 2026-10-04 |
| | investment_deposit | 227.74 | 18 | done_this_month | 2026-10-18 |
| | utilities_payment (3/month) | 117.57 | – | spread | – |
| CUST00002 | salary (in) | 1,592.42 | 15 | done_this_month (arrived late, on 2026-09-30) | 2026-10-15 |
| | housing_payment (4 of 6 months) | 897.39 | 4 | skipped_this_month (last paid 2026-07-04) | 2026-10-04 |
| | utilities_payment (5 of 6 months) | 98.93 | – | spread | – |
| CUST00006 | salary (in) | 3,223.66 | 15 | done_this_month | 2026-10-15 |
| | salary_sweep (out) | 2,885.82 | 16 | done_this_month | 2026-10-16 |
| | utilities_payment | 133.45 | – | spread | – |

## 3. Safe to spend this week — "What can I safely spend this week?"

"This week" is the 7 days after today: `today + 1` … `today + 7`. The number is an estimate (R13). It is the smaller of two limits, so it protects both against overdraft and against spending savings:

```
next_payday     = salary series' next_expected_date (section 2); no salary series -> today + 30
N               = next_payday - today                          (days, at least 1)
essentials/day  = regular_essentials card and non-card purchases (bills and subscriptions excluded) in the window / window days
irregular/day   = unexpected_necessities in the window / window days (one-offs included: a reserve for lumps)

A. balance limit
   free_until_payday = balance - bills_due - (essentials/day + irregular/day) * N - cushion
   balance_limit_7d  = max(free_until_payday, 0) / N * min(7, N)

B. budget limit
   free_month       = income/month - sweep/month - committed/month - (essentials/day + irregular/day) * 30.4375
   budget_limit_7d  = max(free_month, 0) * 7 / 30.4375

safe_to_spend_7d = min(A, B);  binding_limit = whichever is smaller
```

- `balance`: the last `balance_after` on or before today, summed over the customer's accounts (`balance_tx_id`).
- `bills_due`: every recurring outflow except Salary Sweep, due after today and on or before payday. A once-a-month bill counts its typical amount at its typical day in each month of the horizon. This month's unpaid bill counts as due tomorrow if at most 7 days late, and is taken as skipped if later. A bill paid several times a month counts `typical_month * N / 30.4375`. A recurring investment deposit counts too (team-lead decision): it is the customer's own saving plan, and the explanation says so ("your monthly saving of X € is set aside").
- `income/month`, `sweep/month`, `committed/month`: sums of `typical_month_eur` of the recurring salary and other-income series, the salary_sweep series, and the other out-series (investment deposits included).
- `cushion`: `app.cushion_eur`, default **100 €**, configurable (team-lead decision).
- `status`: `nothing_free` if the result is 0; `below_usual` if it is under the customer's usual everyday spending per 7 days (non-one-off, from the window); else `ok`.

**Output** (`03_safe_to_spend.sql`, one row per customer): `safe_to_spend_7d_eur`, `binding_limit`, `balance_limit_7d_eur`, `budget_limit_7d_eur`, `free_until_payday_eur`, `free_month_eur`, `balance_eur`, `balance_tx_id`, `bills_due_eur`, `essentials_reserve_eur`, `irregular_reserve_eur`, `cushion_eur`, `next_payday`, `days_to_payday`, `salary_status`, `income_month_eur`, `sweep_month_eur`, `committed_month_eur`, `essentials_month_eur`, `irregular_month_eur`, `window_days`, `usual_everyday_7d_eur`, `status`, `week_start`, `week_end`, and the safe-to-save columns of section 3.1. The bills behind `bills_due_eur` are the per-bill output of section 3.2.

**Evidence.** Inputs: `balance_tx_id`; the recurring series of section 2; the basket rows of section 1 for the run-rates.

**Edge cases.**
- Payday tomorrow (N = 1): the balance limit spreads the free money over one day; the budget limit then usually binds.
- Salary late this month: `salary_status = late`, payday = last day of the month (conservative).
- Balance already below the reserves: `free_until_payday < 0` → 0, `nothing_free`.
- Salary not paid on its typical day: still `upcoming`, payday tomorrow (N = 1); see the status table in section 2.
- No salary series: payday assumed in 30 days, `salary_status = no_salary_series`. The budget limit still counts any other recurring income (Other Income in at least 4 of 6 months); with none it is 0, so the result is 0 and the coach should say it cannot estimate.
- No history inside the window (first transaction in the current month): the row is still returned, with run-rates 0 and `window_days = 0`.
- Sweep customers: income minus sweep is small, so the budget limit is small and usually binds.

**Worked numbers** (today 2026-09-30, week 2026-10-01 … 2026-10-07, payday 2026-10-15, N = 15):

| | CUST00001 | CUST00002 | CUST00006 |
|---|---|---|---|
| balance | 4,723.58 | 1,539.16 | 4,569.47 |
| bills due before payday | 586.32 = housing 528.38 + utilities 117.57 × 15/30.4375 | 946.14 = housing 897.39 (Oct) + utilities 48.75; September's housing taken as skipped | 65.76 (utilities only; sweep excluded) |
| essentials reserve (15 days) | 312.55 | 224.50 | 16.72 |
| irregular reserve (15 days) | 201.23 | 70.04 | 16.84 |
| cushion | 100 | 100 | 100 |
| free until payday → balance limit 7d | 3,523.49 → 1,644.29 | 198.47 → 92.62 | 4,370.15 → 2,039.40 |
| income − sweep − committed − essentials − irregular per month | 2,364.88 − 0 − 873.69 − 634.21 − 408.33 = 448.66 | 1,592.42 − 0 − 996.32 − 455.55 − 142.13 = −1.59 | 3,223.66 − 2,885.82 − 133.45 − 33.93 − 34.16 = 136.30 |
| budget limit 7d | 103.18 | 0.00 | 31.35 |
| **safe to spend 7d** | **103.18** (budget) | **0.00** (budget), nothing_free | **31.35** (budget) |
| usual everyday spending / 7 days | 91.80 → ok | 87.92 | 11.47 → ok |

Checked with an earlier today: at 2026-09-14 CUST00001's salary is `upcoming`, payday 2026-09-15 (N = 1) and the result is 86.98; at 2026-05-20 (that month's salary came on the 29th) it is `late`, payday 2026-05-31 and the result is 82.94.

### 3.1 Safe to save (#33)

"How much could I move to savings now?" Built only from what safe to spend already computes:

```
everyday/day          = everyday_spending in the window, one-offs left out / window days   (the rate behind usual_everyday_7d)
everyday_until_payday = everyday/day × N
safe_to_save          = max(free_until_payday − everyday_until_payday, 0)          a stock: money on the account now
everyday_month        = everyday/day × 30.4375
safe_to_save_monthly  = max(free_month − everyday_month, 0)                         a flow: what is typically left per month
```

Two figures answer two questions. The formulas are defined only here.
- **`safe_to_save_monthly` is the headline** (product decision): a flow, what a typical month leaves after commitments, both reserves and usual everyday spending.
- **`safe_to_save` is the second line:** a stock, the money on the account beyond what is needed until payday. For a customer with savings on a current account it can be large, so it is explained in one sentence and never comes with a call to action.

**Why the month leaves nothing.** When `safe_to_save_monthly` is 0, a reason is given from the data:

```
if free_month < 0:   reason = essentials_exceed_income,  amount = −free_month (the monthly shortfall, a positive number)
else:                reason = largest_everyday_category, amount = that category's everyday_month figure
                     (free_month ≥ 0 but free_month − everyday_month ≤ 0)
```

- **The rule is on the sign of free month** (team-lead decision on the #33 review).
  - If free month is already negative, bills, the saving the customer set up, usual essentials and the reserve exceed income, so even no everyday spending would leave nothing. In that case the card shows the shortfall as its own positive component and never a negative free month.
  - Otherwise the month leaves nothing because of everyday spending.
- **`largest_everyday_category`** is the `everyday_spending` category (after the basket rules and labels of section 1) with the largest window total, one-offs left out. Its amount uses the same basis as `everyday_month`: window total ÷ window days × 30.4375. The categories therefore add up to `everyday_month`.
- **Sensitive categories:** none is ever named (R9). `everyday_spending` holds none today, and if one ever appeared, the next category would be named.
- **Rounding:** derived figures are computed from unrounded values and rounded once. A figure can therefore differ by 0.01 from the same sum of displayed figures, for example safe to save 12,360.83 against 12,656.12 − 295.28 = 12,360.84.

**Not the same as the down-payment capacity.** `safe_to_save_monthly` uses the planning income of section 3 (`income_month_eur`, the median of the recurring income series) and keeps both reserves. The down-payment capacity of section 11 uses the average income that actually arrived (`net_income_month_eur`, see "Two income figures" in section 5) and no reserves. The two numbers differ on purpose: for Sanna, 184.61 against 547.79 a month.

- **What it means.** Free until payday is what is left after the bills due before payday, both reserves and the cushion. Safe to save also keeps the usual everyday spending until payday. If the customer moves the whole amount, what is left still covers bills, reserves, the cushion and a normal everyday spending pace until payday.
- **Not additive with safe to spend.** Both come out of the same free money. Moving money to savings lowers the balance limit of section 3 by the same amount spread over the days to payday. The coach never presents the two as separate pots.
- **R13 and R7.** It is an estimate, shown with its formula in plain words. It is not investment advice: the coach never says where to put the money (no product, no instrument).
- **Edge cases.**
  - Free until payday at or below the usual everyday spending until payday gives 0, and the coach says there is nothing to spare before payday.
  - With no salary series, payday is assumed in 30 days (section 3), so the result is conservative.
  - Payday today: N is never 0. A salary not yet paid on its typical day is expected tomorrow (N = 1), so everyday until payday is one day of everyday spending; once it is paid, payday is next month's.
  - No everyday spending in the window: everyday until payday and everyday month are 0, and both figures equal their free amounts (or 0).
  - Sweep customers: the balance is small, so the result is small.
- **Output** (columns of `03_safe_to_spend.sql`, #53), all computed from the unrounded terms and rounded once:
  - `everyday_until_payday_eur` = everyday/day × N; `safe_to_save_eur` = max(free until payday − that, 0).
  - `everyday_month_eur` = everyday/day × 30.4375; `safe_to_save_monthly_eur` = max(free month − that, 0).
  - `essentials_shortfall_month_eur` = max(−free month, 0): the monthly shortfall as a positive amount, 0 when free month is not negative.
  - `save_reason`: `null` unless `safe_to_save_monthly_eur` is 0.00; then `essentials_exceed_income` if free month < 0, else `largest_everyday_category`.
  - `save_reason_category`: the category for `largest_everyday_category` (Health is never named, R9), else `null`.
  - `save_reason_month_eur`: the shortfall for `essentials_exceed_income`, the category's figure for `largest_everyday_category`, else `null`.
- **Evidence.** Free until payday (with its own inputs) and the everyday rows of the window that are not one-offs.
- **Worked numbers** (CUST00860, today 2026-09-30, N = 15; everyday/day = 3,602.44 / 183 = 19.685):

| | No review = after "needed" (1.1) | Review pending, or after "I chose it" |
|---|---|---|
| Free until payday | 12,567.56 | 12,656.12 |
| Everyday until payday (× 15) | 295.28 | 295.28 |
| **Safe to save** | **12,272.28** | **12,360.83** (the irregular reserve is 88.56 lower) |
| Free month | 783.79 | 963.49 |
| Everyday month (× 30.4375) | 599.18 | 599.18 |
| **Safe to save monthly** | **184.61** | **364.31** (the irregular spending per month is 179.70 lower) |

Three more customers, today 2026-09-30 (no reviews):

| | CUST00849 (persona Aleksi) | CUST00019 | CUST00002 |
|---|---|---|---|
| Free month = income − sweep − committed − (essentials + irregular) per month | 2,088.35 − 0 − 712.67 − 525.97 − 124.23 = **725.47** (the rounded parts add up to 725.48) | 2,548.69 − 0 − 1,171.32 − 694.69 − 283.79 = **398.89** | 1,592.42 − 0 − 996.32 − 455.55 − 142.13 = **−1.59** (the rounded parts add up to −1.58) |
| Everyday month (one-offs left out) | 525.52 | 585.33 | 382.30 |
| **Safe to save monthly** | **199.95** = 725.47 − 525.52 | **0.00**: 398.89 − 585.33 = −186.45 | **0.00**: free month is already negative |
| Reason | none: the month leaves money | free month ≥ 0, so `largest_everyday_category`: **Restaurants**, 186.93 a month (then Entertainment 157.48, Lifestyle 139.37 and Travel 101.55; the four add up to 585.33) | free month < 0, so `essentials_exceed_income`, shortfall **1.59** a month |
| Free until payday − everyday until payday | 819.62 − 258.98 = **560.64** | 573.53 − 288.46 = **285.07** | 198.47 − 188.40 = **10.07** |

The three sample customers of section 3, today 2026-09-30 (no reviews; N = 15):

| | CUST00001 | CUST00002 | CUST00006 |
|---|---|---|---|
| Free until payday − everyday until payday | 3,523.49 − 196.72 = **3,326.77** | 198.47 − 188.40 = **10.07** | 4,370.15 − 24.59 = **4,345.56** |
| Free month − everyday month | 448.66 − 399.17 = **49.48** (the rounded parts give 49.49) | −1.59, already negative: **0.00** | 136.30 − 49.89 = **86.41** |
| Reason | none | `essentials_exceed_income`, shortfall **1.59** | none |

- **How these were computed:** the columns of `03_safe_to_spend.sql` over the default sample range and for CUST00849 and CUST00860 one at a time, one read-only connection with `statement_timeout = '60s'`. The same values are checked in `core/tools/tests/test_tools_db_safe_to_save_bills.py`.
- **How often each case occurs:** in the 99-customer sample, 5 customers have a negative free month (CUST00002, 09, 34, 78, 86), and 35 have a positive free month that everyday spending uses up.

### 3.2 Bills due before payday, per bill (#44)

The bills behind `bills_due_eur`, one row per bill that falls due after today and up to and including the next payday: `core/metrics/03_safe_to_spend_bills.sql`. Its method id is `safe_to_spend.bill_due_eur@1`.

- **One definition.** The file's text from `SET statement_timeout` to the line "end of the part shared with 03_safe_to_spend_bills.sql" is identical to `03_safe_to_spend.sql`, and a test checks it. That part ends with `bill_items`, one unrounded term per bill. 03's `bills_due_eur` is the sum of those terms, rounded once.
- **The term.** A once-a-month bill counts its typical month for each due date up to and including payday (section 3: this month's unpaid bill is due tomorrow if at most 7 days late, and skipped if later). A bill paid several times a month counts typical month × N / 30.4375. Salary Sweep is never a bill.
- **Columns:**
  - `customer_id`, `series_kind`, `series_key`, `category`.
  - `label`: English, for reading the output. The app shows the tool's labels, an alias for a merchant.
  - `status`: section 2: `spread`, `done_this_month`, `upcoming`, `late` or `skipped_this_month`. A once-a-month bill already paid this month, or skipped, can still be due before payday through next month's date.
  - `typical_month_eur`, `occurrences` (due dates before payday; 0 for a spread bill), `first_due_date`.
  - `pro_rata_days` (N for a spread bill, else 0), `bill_due_eur`, `next_payday`, `days_to_payday`.
- **Rounding.** Each row is rounded on its own, and the total once. The rows therefore add up to `bills_due_eur` or differ from it by up to 0.01 per row: each row's rounding moves it by at most 0.005. In the sample: exact for 76 of 99 customers, +0.01 for 23. A customer has at most 2 bills there. The `get_recurring_bills` tool shows the same per-bill values (a test compares them).
- **Worked numbers** (today 2026-09-30, payday 2026-10-15, N = 15):

| Customer | Bill | Status | Due before payday |
|---|---|---|---|
| CUST00001 | housing_payment | done_this_month (next on 2026-10-04) | 528.38 |
| | utilities_payment | spread, 117.57 × 15 / 30.4375 | 57.94 |
| | **total = `bills_due_eur`** | | **586.32** |
| CUST00002 | housing_payment | skipped_this_month (next on 2026-10-04) | 897.39 |
| | utilities_payment | spread, 98.93 × 15 / 30.4375 | 48.75 |
| | **total** | | **946.14** |
| CUST00006 | utilities_payment | spread, 133.45 × 15 / 30.4375 (the sweep is not a bill) | 65.76 |
| | **total** | | **65.76** |

## 4. What-if savings — "How could I save more?"

An estimate (R13): "if the next months look like the average of the last 6 complete months, cutting X by p% saves …".

```
baseline_month = sum(out_eur) of the selection in the window, one-offs and regular essentials excluded / n_months
saving_month   = baseline_month * p / 100
saving_week    = saving_month * 7 / 30.4375
saving_year    = saving_month * 12
```

**What may be cut** (team-lead decision): a what-if never proposes cutting `regular_essentials`. Those rows of a selection are left out of the baseline and shown in `regular_excluded_eur`. `everyday_spending` is the normal target. `unexpected_necessities` may be cut, but the row's `status` is `estimate_with_caveat` and the coach says these are needed costs that only sometimes can be reduced. A selection with nothing cuttable gets `status = not_offered` and zero savings: for example `category:Groceries`, which is all regular essentials.

Selection (`app.whatif`): `category:<name>`, `mcc:<code>[,<code>…]`, `basket:<key>` or `merchant:<id>`; default `category:Restaurants`. Cut `app.whatif_pct`, default 20. Examples: dining out −20% = `category:Restaurants`; taxis −50% = `mcc:4121` with 50; all everyday spending −10% = `basket:everyday_spending` with 10.

**Output** (`04_what_if.sql`, one row per customer with spending in the selection): `selection`, `cut_pct`, `status` (`estimate`, `estimate_with_caveat`, `not_offered`), `baseline_month_eur`, `saving_month_eur`, `saving_week_eur`, `saving_year_eur`, `n_tx`, `one_off_excluded_eur`, `n_one_off`, `regular_excluded_eur`, `n_months`, `period_start`, `period_end`. Method text for the card: "Average of your last 6 full months (one-off purchases left out), cut by p%".

**Evidence.** Rows of the selection in the window with `is_one_off = false` and a basket other than `regular_essentials`.

**Edge cases.** No spending in the selection: no row; the coach says there is nothing to cut. Only regular essentials or one-offs in it: `not_offered`. One-offs are reported in `one_off_excluded_eur` so the coach can mention them. Checked: `category:Groceries` gives `not_offered` for CUST00001 and CUST00002; `basket:unexpected_necessities` −20% gives `estimate_with_caveat`, 81.83 a month for CUST00001.

**Worked numbers** (dining out −20%):

| Customer | Restaurants / month | Saving / month | / week | / year | One-offs left out |
|---|---|---|---|---|---|
| CUST00001 | 56.86 (20 tx) | 11.37 | 2.62 | 136.45 | 0 |
| CUST00002 | 92.18 (33 tx) | 18.44 | 4.24 | 221.23 | 0 |
| CUST00006 | 15.56 (14 tx) | 3.11 | 0.72 | 37.33 | 0 |

## 5. Spender profile — "What kind of spender am I?"

Features over the window (all per month unless noted):
- `net_income` = (income − Salary Sweep) / n_months, where income = Salary + Other Income (Invest Withdraw is not income; section 2.3)
- `spend` = spend flow / n_months; `saving` = Invest Deposit / n_months
- `keep_rate` = (net_income − spend) / net_income, in % (investment deposits count as kept); only computed when net_income > 0
- basket shares of spend; `one_off_share`: one-off purchases outside Health as a share of spend (Health one-offs are left out so that health spending can never set a label, R9)
- `everyday_weekend_pct`: share of everyday spending on Saturday or Sunday
- `everyday_tx_month`, `everyday_avg_ticket_eur`, `top_everyday_category`
- `months_out_over_in`: months where spend + saving exceeded that month's income − sweep (same income definition)
- `n_tx_below_zero`: transactions that left the balance below 0

**Primary label** (first rule that matches):

| Order | Key | Rule |
|---|---|---|
| 0 | `not_enough_income_data` | net_income ≤ 0 or no income in the window (for example a sweep larger than the salary): no keep rate, so no spending verdict; the coach says the account does not show enough income |
| 1 | `stretched` | keep_rate < 0 (spends more than comes in) |
| 2 | `big_ticket` | one_off_share ≥ 5% |
| 3 | `everyday_heavy` | everyday share ≥ 30% |
| 4 | `saver` | keep_rate ≥ 20% |
| 5 | `steady` | otherwise |

**Traits** (any number of the five): `salary_moved_elsewhere` (a sweep customer, section 2.3), `went_below_zero` (n_tx_below_zero > 0), `regular_investor` (saving > 0), `weekend_spender` (weekend share ≥ 45%; an even spread is 29%), `frequent_small_purchases` (≥ 12 everyday purchases a month).

The thresholds are fixed constants, set once from the sample's distribution (keep_rate p33 = 0.8%, p67 = 19.5%; everyday share p67 = 26.2%, p90 = 37.1%; one-off share p90 = 6.1%; weekend share p67 = 42.2%; everyday purchases a month p67 = 11.8). They do not depend on who is in the run. On the sample the labels split as stretched 29, steady 27, saver 24, everyday_heavy 12, big_ticket 7 (no sample customer is `not_enough_income_data`).

**Two income figures.** `net_income_month_eur` here is what actually arrived on average (mean of Salary + Other Income − Sweep over the window: 2,388.42 for CUST00001). Safe to spend (section 3) uses `income_month_eur`, the median of the recurring salary series (2,364.88), because it plans the next month and should not count one-off income. The coach quotes the profile figure when describing the past and the safe-to-spend figure when planning.

R9: no feature uses Health or health MCCs on their own; labels and traits contain no sensitive terms.

**Output** (`05_spender_profile.sql`, one row per customer): `profile`, `traits`, `keep_rate_pct`, `net_income_month_eur`, `spend_month_eur`, `saving_month_eur`, `regular_share_pct`, `unexpected_share_pct`, `everyday_share_pct`, `one_off_share_pct`, `everyday_weekend_pct`, `everyday_avg_ticket_eur`, `everyday_tx_month`, `top_everyday_category`, `months_out_over_in`, `n_tx_below_zero`, `n_months`, `period_start`, `period_end`.

**Evidence.** The window's transactions per flow and basket; the label cites the feature values that decided it.

**Worked numbers:**

| Customer | Profile | Traits | Keep rate | Net income / month | Spend / month | Everyday share |
|---|---|---|---|---|---|---|
| CUST00001 | steady | regular_investor | 12.6% | 2,388.42 | 2,087.92 | 19.2% |
| CUST00002 | stretched | went_below_zero (11 tx), frequent_small_purchases (13.3/month) | −4.5% | 1,628.40 | 1,702.17 | 25.3% |
| CUST00006 | saver | salary_moved_elsewhere | 24.8% | 337.13 | 253.54 | 19.7% |

## 6. Peer benchmark by age band and postal area

An estimate (R13): "people like you" are customers in the same age band and area.

- Age bands: 18–24, 25–34, 35–44, 45–54, 55–64, 65–74, 75+.
- Areas: `area3` = first 3 digits of the postal code (30 areas in the data); `city` = first 2 digits (00 Helsinki, 01 Vantaa, 02 Espoo and Kauniainen).
- Levels, most specific first: age band + area3 → age band + city → age band → all. The area is widened first and the age band is given up last, because age explains spending more than the postal area (team-lead decision). The customer gets the first level with **at least 20 other peers** (`app.peer_min_n`). If no level has enough, the row takes the coarsest level, with `shown = false` and every peer statistic NULL (for example a one-customer run without marts, `peer_n = 0`). Small groups are never shown: this protects both statistics and privacy.
- Sweep customers (section 2.3) never enter a peer group (their spending happens elsewhere), and their own rows say `comparable = false` and `shown = false`, with NULL statistics.
- Metrics (month averages over the window): total spend, the three baskets, and the categories Groceries, Restaurants, Transportation, Entertainment, Lifestyle, Travel, Home & Tech, Utilities, Housing. **Health is not benchmarked** (R9).
- `percentile` = share of the other peers in the group who spend less; `vs_median_pct` = you / peer median − 1.
- Who is counted: `peer_median`, `peer_p25` and `peer_p75` describe the whole group, the customer included (one value among 21 or more moves them little, and the group statistics can then be computed once per group). `peer_n` and `percentile` count only the other members.

**Output** (`06_peer_benchmark.sql`, one row per customer and metric): `you_month_eur`, `peer_median_month_eur`, `peer_p25_month_eur`, `peer_p75_month_eur`, `percentile`, `vs_median_pct`, `shown`, `comparable`, `peer_level`, `peer_group`, `peer_n`, `peer_source` (`marts` or `range`), `period_start`, `period_end`. The coach uses a row only when `shown` is true.

**Evidence.** The customer's rows for the metric; the peer group definition and its n. Peer rows themselves are never exposed.

**Who the peers are.** When the marts of section 8 hold rows for `as_of = today`, the peers are the whole population (5,100 customers; output column `peer_source = marts`). Every age band then has at least 121 comparable customers (75+ is the smallest), so the "all" level is never needed and the file reads only the age bands of the customers in the range. Without a build for that day the file falls back to the customers inside the range (`peer_source = range`); with 99 customers that mostly means age band or all. The customer's own values are always computed live. Statistics Finland's open Paavo data by postal code (median income, household size) could later refine "people like you"; it is not used here.

On the full population, the sample's 1,287 rows split as: 1,079 compared within age band + area3, 143 within age band + city, and 65 not comparable (the 5 sweep customers × 13 metrics). 261 of the 5,100 customers are sweep customers.

**Worked numbers** (full population, marts built for 2026-09-30):

| Customer | Metric | You / month | Peer median | Percentile | Level (other peers) |
|---|---|---|---|---|---|
| CUST00001 | total spend | 2,087.92 | 3,027.77 | 10 | 55–64 + area 009 (31) |
| CUST00001 | Restaurants | 56.86 | 188.90 | 16 | 55–64 + area 009 (31) |
| CUST00002 | total spend | 1,702.17 | 3,138.52 | 4 | 45–54 + area 005 (93) |
| CUST00002 | everyday spending | 430.29 | 850.10 | 26 | 45–54 + area 005 (93) |
| CUST00006 | total spend | 253.54 | not shown | not shown (comparable = false) | 35–44 + area 007 (132) |

## 7. Grocery store price index and switch saving

An estimate (R13) with a strong caveat: the data has **ticket totals, not item prices**. A store with a higher index means "people pay more per visit there than they pay elsewhere"; that mixes price level with basket size and store type.

**Model** (customer-normalised, two-way fixed effects): for grocery card purchases of the last 365 days,

```
ln(ticket) = a_customer + b_merchant + e
```

Fitted by alternating means (3 rounds, starting from b = 0; on the full population the last round moves the merchant effects by at most 0.000006) on customer × merchant cells with sufficient statistics `n, Σy, Σy²`. The cells come from `metric_grocery_cells` when the marts are built for `as_of = today`, otherwise from the customers in the range. The customer effect removes "this person buys big baskets"; `b_merchant` is what remains. Effects are centred so that the visit-weighted average store is 0%.

- `index_pct = 100 × (exp(b) − 1)`; `se = σ / sqrt(n_visits)` with σ pooled from the residuals (degrees of freedom = visits − customers − merchants + 1); 95% interval shown. If no degrees of freedom are left (a tiny range), σ is NULL: no interval, no flag, and switch status `not_measurable`.
- Caveat: this standard error treats the customer effects as known. It ignores their own uncertainty, so the intervals are somewhat optimistic (too narrow); the strict |z| ≥ 3 rule below partly offsets that.
- A store is shown only with 30+ visits. It is flagged as different from average only if |b| ≥ 3·se (with ~70 stores, 1.96·se would give about 3 false flags by chance).
- **Switch saving.** For each customer: the home store (largest grocery spend in the 365 days) against the lowest-index store of the **same MCC** that the customer already uses (3+ visits) and that has 30+ visits overall. `ticket_gap = 1 − exp(−(b_home − b_alt))`. Only if `b_home − b_alt ≥ 3 × sqrt(se_home² + se_alt²)`: `est_saving_month = home_spend_month × ticket_gap`, status `estimate`. Otherwise saving 0 and status `within_noise`, `already_lowest`, `not_measurable` or `no_alternative`.
- **When the coach shows it** (team-lead decision): the store index and switch savings are shown only when the full-population run finds stores that pass the |z| ≥ 3 rule. Otherwise the coach says the difference between stores is not measurable from this data.

**Output** (`07_store_price_index.sql`, two result sets). Per merchant: `merchant_id`, `mcc`, `n_visits`, `n_customers`, `avg_ticket_eur`, `index_pct`, `ci95_low_pct`, `ci95_high_pct`, `differs_from_average`, `shown`, `max_last_step` (convergence). Per customer: `home_merchant_id`, `home_index_pct`, `home_spend_month_eur`, `alt_merchant_id`, `alt_index_pct`, `ticket_gap_pct`, `ticket_gap_ci95_low_pct`, `status`, `est_saving_month_eur`, `period_start`, `period_end`.

**Evidence.** The customer's grocery transactions at the two stores; the index's method and n.

**What the sample shows (honest result).** 80 grocery merchants, 68 with 30+ visits. Index from −14.1% to +9.0% (SD 4.8 points), but the median 95% interval is ±10.0% (from ±3.1% for the busiest store to ±16.9%). **No store differs from average at |z| ≥ 3, and no customer gets a switch estimate**: on 99 customers the index is noise. The model converges: with 5 rounds the last step was 0.000000; with the 3 rounds used now it is 0.00008 on the sample, about 0.008 index points. The sample alone could not settle it, so the full population was run.

**Full population (the result the coach uses).** 203,680 customer × store cells from 5,100 customers, 80 grocery stores, each with 414 to 45,200 visits (all shown). The median 95% interval shrinks to ±1.45% (±0.45% to ±4.5%), as predicted. But the stores barely differ once the customer is taken into account: the index runs from −3.7% to +1.6% with a spread (SD) of 0.78 points, which is about the size of the noise. The −3.4% … +4.5% spread of the first raw check came from who shops where, not from the stores. **No store passes the |z| ≥ 3 rule, and no sample customer gets a switch estimate** (73 within_noise, 17 no_alternative, 9 already_lowest). At the looser 95% level, 2 of 80 stores differ, which is about what chance alone would produce (about 4).

**Conclusion.** Following the team-lead rule, the coach does **not** show a store index or a switch saving for this data. It says that the difference between grocery stores is not measurable from these transactions. 07 stays in place so the check can be re-run after a new data load.

"Not measurable" in that sentence is plain language, not a status. It covers the API's switch statuses `within_noise`, `no_alternative` and `already_lowest`. The status `not_measurable` is narrower: no interval could be computed at all (no degrees of freedom left).

**Worked numbers** (full population):

| Customer | Home store (index) | Home spend / month | Lowest-index alternative (index) | Status | Saving |
|---|---|---|---|---|---|
| CUST00001 | MRC-GRO-0032 (−0.1%) | 57.52 | MRC-GRO-0073 (−0.4%) | within_noise | 0 |
| CUST00002 | MRC-GRO-0032 (−0.1%) | 46.67 | MRC-GRO-0022 (−0.3%) | within_noise | 0 |
| CUST00006 | MRC-GRO-0036 (+0.3%) | 9.83 | none with 3+ visits | no_alternative | 0 |

Note that customers spread their grocery spend over many stores (15 to 74 different grocery merchants each over the two years, 56 on average), so even a real 3% gap at the home store is worth only a few euros a month.

## 8. Batched precompute for the full population (`core/marts/`)

The database has 2 GB RAM and 25 connections, and a full-table aggregate has restarted it before. Metrics 1–5 are per customer and run on demand for one customer. Metrics 6 and 7 need everyone, so they read three small mart tables (`core/marts/schema.sql`):

| Table | One row per | Rows (as_of 2026-09-30) |
|---|---|---|
| `metric_customer_month` | customer × window month × metric (spend total, basket, category; no Health) | 299,971 |
| `metric_peer_flags` | customer: age band, area3, city, comparable (not a sweep customer), n_months | 5,100 |
| `metric_grocery_cells` | customer × grocery store over 365 days: n, Σ ln ticket, Σ ln² ticket, spend | 203,680 |

Every row carries `as_of`, the DEMO_TODAY it was built for. 06 and 07 use the marts only when the build for their own "today" is **complete**: `metric_peer_flags` must hold at least as many rows for that `as_of` as `customers` has. Each batch writes all three tables in one transaction, so complete flags mean complete marts. During a first build for a new day, or after a stopped build, both files fall back to the range path, so partial statistics are never served and no customer silently loses a row. A build for another day can never leak in. The three tables take 72 MB.

`core/marts/build.py` fills them in 52 batches of 100 customers, using one connection with `statement_timeout = 60s` and a pause between batches. Each batch is one transaction that deletes its range for that `as_of` and inserts it again, so batches are idempotent, and a run can resume with `--from CUSTxxxxx`. A batch that times out is split in half and each half is tried once; then the script stops and names the range. The classification SQL is read from the shared block in `02_baskets.sql`, so the marts cannot drift from metrics 1–6.

The first full build took 234 s for 52 batches. The slowest batch took 12.0 s, while the database was busy with other work; idle batches take 1.3–1.8 s. There were no timeouts. Rebuild once after each data load, or when DEMO_TODAY changes, not per request (README, "Data").

## 9. How it was verified

Every file was run on the sample under `statement_timeout = '60s'` after rebasing onto `origin/main`, one connection at a time:

| File | Rows | Server idle | Server busy |
|---|---|---|---|
| 01_recurring.sql | 315 | 0.74 s | 2.07 s |
| 02_baskets.sql | 297 | 0.53 s | 2.89 s |
| 03_safe_to_spend.sql | 99 | 1.25 s | 8.05 s |
| 04_what_if.sql | 96 | 0.62 s | 2.97 s |
| 05_spender_profile.sql | 99 | 2.60 s | 14.71 s |
| 06_peer_benchmark.sql (marts) | 1,287 | – | 14.88 s |
| 07_store_price_index.sql (marts) | 80 + 99 | – | 8.64 s |

Times are wall-clock from a laptop client, including network round trips. "Busy" runs happened while the database was slow for a reason we could not identify: two snapshots showed no other active session in our database, but short queries from other sessions or load elsewhere on the server would not show there. In those periods large reads were 3–6× slower, and once 14× slower (05 took 36.5 s on the sample).

**Per customer (the app's on-demand path)**, one customer per call, for CUST00001, CUST00002 and CUST00006:

| File | Server idle | Server busy |
|---|---|---|
| 01–05 (each) | 11–36 ms | 10–213 ms |
| 06_peer_benchmark.sql | 0.1–0.5 s | 0.7–3.5 s |
| 07_store_price_index.sql | 1.6–1.7 s | 7.5–8.9 s |

Metrics 1–5 need no cache or mart for the demo: one customer reads a few hundred rows through the customer index. 07 refits the whole index on every call. The index is the same for every customer on a given day, so if it is ever shown it should be computed once per data load (follow-up). With this data it is not shown (section 7).

- `EXPLAIN` of every statement that reads `transactions` shows an `Index Scan` on `tx_customer_time` (07: `tx_customer_category`) with the customer range as the `Index Cond`; no `Seq Scan on transactions` anywhere.
- With `app.demo_today = 2026-09-14` all seven files run, and every period moves: the 6-month window becomes 2026-03-01 … 2026-08-31, the safe-to-spend week 2026-09-15 … 2026-09-21, the store index year 2025-09-15 … 2026-09-14. 01 and 03 were also checked at 2026-05-20 (late salary); see sections 2 and 3.
- One-customer runs (`[CUST00006, CUST00007)`) return the same numbers as the sample run for files 01–05.
- The override path was run with two rows (section 1).
- Marts (#21) were checked several ways. Spot check: CUST00001's May 2026 rows in `metric_customer_month` equal direct sums from `transactions` (Groceries 610.20 over 9 transactions, total spend 2,125.15 over 26). The basket rows, which go through the shared classification block, give the same month averages as section 1 (1,278.77 / 409.17 / 399.99). The README command was run as written in Git Bash on the last batch. Re-running `build.py --from CUST05000` leaves all three row counts unchanged. A forced timeout (`--timeout-ms 5`) splits the batch, stops at the first half and names it, with the rows untouched. With `app.demo_today = 2026-09-14` (no build for that day), 06 falls back to the range (`peer_source = range`), and so does 07 (856 visits at the busiest store, as on the sample; last step 0.00008).
- The complete-build gate was proven without touching the shared marts. In one session, a temp table named `metric_peer_flags` held only 2,599 of the 5,100 flags; unqualified names resolve to the session's temp schema first, so this simulates a stopped build. For CUST00001, 06 then returned `peer_source = range` instead of `marts`, and 07 fitted on the range (11 visits at the busiest store instead of 45,200). After dropping the temp table both used the marts again.
- `build.py` never prints a driver message, because it can contain the connection string. A malformed URL (in quotes, or with a leading space) gives `stopped: could not connect (ProgrammingError); check DATABASE_URL`, and an unknown host gives the same with `OperationalError`; both were tested with a fake URL. A failure during a batch prints the batch, the error class and the SQLSTATE. `--batch 0`, `--from` after `--to` and a malformed `DEMO_TODAY` stop with a one-line message.
- The worked numbers above are copied from these runs. The runs used a psycopg 3 client (no psql on the machine): it sets the three `app.*` settings, runs the whole file in one call and prints the time and rows; `psql -f` gives the same result.

## 10. Open questions for Renat

Decisions 2 to 7 were taken by the team lead and are the documented defaults; Renat can overrule them.

1. **Salary Sweep. Open.** It is monthly for 5% of customers (the issue says yearly). Until the bank's people answer, it is treated as a transfer: netted out of income, and sweep customers are left out of peer groups (section 2.3).
2. **Basket edge cases. Decided:** as proposed. Home & Tech (also its spikes) → unexpected necessities; Travel and taxi → everyday spending; parking and fuel → regular essentials.
3. **Cushion. Decided:** 100 € by default, configurable with `app.cushion_eur`.
4. **Investment deposits. Decided:** a recurring investment deposit is reserved in safe to spend. It is the customer's own saving plan, and the explanation says so.
5. **What-if scope. Decided:** never propose cutting regular essentials; everyday spending is the target, unexpected necessities only with a caveat (section 4, implemented in `04_what_if.sql`).
6. **Store switch. Decided:** shown only when the full-population run finds stores that pass the significance rule; otherwise the coach says the difference is not measurable. Result of the full run (#21): no store passes, so it is not shown (section 7).
7. **Peer groups. Decided:** at least 20 other peers; the area widens first, the age band last (section 6). Paavo open data is a later issue.
8. **Spike labels. Decided** (owner, on issue #33):
   - A spike with a pending review is `unclassified`: in no basket and not in the reserve.
   - "Needed" adds it to the reserve, so safe to spend goes down (Sanna 221.58 → 180.26).
   - "I chose it" leaves safe to spend unchanged.
   - No answer raises safe to spend above the value shown while the question was pending, and an expired review cannot be answered.
   - A customer without a pending review keeps every published number (section 1.1).

## 11. Optional, after the MVP: down payment plan (`down_payment_plan`)

Answers "How much could I put aside for a down payment, and how long would it take?". An estimate (R13), definition only, no SQL prototype yet. It never predicts the bank's decision, never says whether a loan would be approved and never scores the user (R8). It does not recommend a product or where to keep the money (R7); for a mortgage it points to an S-Pankki adviser.

**Inputs from the user:** `target_eur` (the down payment they aim for; the coach does not suggest a home price) and optionally `start_eur` (what they already have set aside; default 0, because account balances and investment holdings are not the same thing as savings set aside).

```
capacity_month   = net_income_month - spend_month            (section 5, same window: mean of the 6 complete months)
                 = keep_rate * net_income_month               (investment deposits count as already put aside)
capacity_plan    = capacity_month + sum(saving_month_eur of the what-if cuts the user picks)   (section 4)
months_to_target = ceil((target_eur - start_eur) / capacity)  if capacity > 0, else "not reachable at this pace"
```

Also returned: the lowest and highest monthly keep in the window and how many months were negative, so the coach can say how steady the pace is. The output is a number object per value, with `period` = the window and `method` = "average of your last 6 full months of income minus spending".

**Edge cases.**
- Capacity ≤ 0: no months figure. The coach shows the what-if cuts that would make it positive.
- `salary_moved_elsewhere` (Salary Sweep): the account does not show the whole income, so the plan is not estimated from it. The coach asks the user instead.
- Under 6 months of history: use the months available and say so.
- No interest, inflation, price or rate changes are modelled. The caveat says so in plain words.

**Illustration** (CUST00001, window 2026-04 … 2026-09; the target is a made-up user input). Monthly keep was 285.98, 590.08, 602.90, −111.54, −133.58 and 569.15 (2 of 6 months negative), so `capacity_month` = 300.50, of which 230.01 is the existing monthly investment deposit. For a 20,000 € target from 0 the result is 67 months. With dining out −20% (+11.37 a month, section 4) it is 65 months. For CUST00002 the capacity is −73.77 a month, so the plan is not reachable at this pace. CUST00006 has a monthly sweep, so the plan is not estimated.

## Rule references

R1 and R2: every number is a column with its period and an evidence filter (section 0). R5: the DEMO_TODAY bound in every query. R9: Health is summed only, never benchmarked or used in labels (sections 1, 5, 6). R13: safe to spend, what-if, peer benchmark and store index are estimates with a stated method and caveat (sections 3, 4, 6, 7).
