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

## 0. Conventions shared by all metrics

**Inputs.** Each file reads session settings and falls back to defaults, so it also runs with no settings at all:

```sql
SET app.demo_today    = '2026-09-30';  -- "today"; default 2026-09-30
SET app.customer_from = 'CUST00001';   -- inclusive; default CUST00000
SET app.customer_to   = 'CUST00002';   -- exclusive; default CUST00100 (the 99-customer sample)
\i core/metrics/03_safe_to_spend.sql
```

For one customer, set the range to `[id, next id)`. Metrics 1 to 5 depend only on the customer's own rows, so a one-customer run returns the same numbers as the sample run. Metrics 6 and 7 depend on who else is in the range (see their sections).

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

In the prototypes the same shape is an empty `overrides` CTE, joined by `LEFT JOIN LATERAL … ORDER BY specificity LIMIT 1`. Output has `overridden` per transaction.

**Output** (`02_baskets.sql`, one row per customer and basket): `month_avg_eur`, `month_avg_excl_one_off_eur`, `one_off_total_eur`, `n_one_off`, `share_pct` (of the customer's spend), `total_eur`, `n_tx`, `n_months`, `period_start`, `period_end`.

**Evidence.** Transactions of the customer with flow spend, `tx_date` in the window, and the basket after the rules above. `sum(out_eur) = total_eur`.

**Edge cases.** No spending in a basket: no row (the API shows 0). Customer with under 6 months of history: `n_months` < 6 and averages divide by it. Category not in the table: `unclassified`, never silently dropped.

**Worked numbers** (window 2026-04-01 … 2026-09-30, month averages):

| Customer | Regular essentials | Unexpected necessities | Everyday spending |
|---|---|---|---|
| CUST00001 | 1,278.77 (61.2%) | 409.17 (19.6%) | 399.99 (19.2%) |
| CUST00002 | 1,129.45 (66.4%) | 142.42 (8.4%); 126.89 without one 93.17 one-off | 430.29 (25.3%); 383.09 without one 283.24 one-off |
| CUST00006 | 169.32 (66.8%) | 34.23 (13.5%) | 49.99 (19.7%) |

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
| not paid, today before typical day | `upcoming` | typical day this month |
| income not paid, past typical day | `late` | last day of this month (or tomorrow if today is the last day) |
| bill not paid, at most 7 days past typical day | `late` | tomorrow |
| bill not paid, more than 7 days past | `skipped_this_month` | typical day next month |

- `late_share_12m` (salary): share of the last 12 months whose salary came on day 26 or later.

**Output** (`01_recurring.sql`, one row per recurring series): `series_kind`, `series_key`, `direction` (in or out), `cadence`, `months_present`, `tx_per_month`, `typical_month_eur`, `cv_month`, `typical_day`, `last_date`, `last_amount_eur`, `last_tx_id`, `n_tx_this_month`, `paid_this_month_eur`, `status`, `next_expected_date`, `late_share_12m`, `period_start`, `period_end`.

**Evidence.** The series' transactions in the window (for typical amounts) plus `last_tx_id`.

### 2.3 Salary Sweep (decision needed)
Default here: a sweep is a **transfer**, not spending and not saving. It reduces the money available on this account (safe to spend uses income minus sweep), it is never reserved as a bill before payday (it follows the salary), and a customer with a monthly sweep is excluded from peer groups (section 6). Open question 1 asks what it really is.

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
- `bills_due`: every recurring outflow except Salary Sweep, due after today and on or before payday. A once-a-month bill counts its typical amount at its typical day in each month of the horizon. This month's unpaid bill counts as due tomorrow if at most 7 days late, and is taken as skipped if later. A bill paid several times a month counts `typical_month * N / 30.4375`. Investment deposits count (they are a commitment the user set up).
- `income/month`, `sweep/month`, `committed/month`: sums of `typical_month_eur` of the recurring in-series, the salary_sweep series, and the other out-series.
- `cushion`: `app.cushion_eur`, default **100 €** (open question 3).
- `status`: `nothing_free` if the result is 0; `below_usual` if it is under the customer's usual everyday spending per 7 days (non-one-off, from the window); else `ok`.

**Output** (`03_safe_to_spend.sql`, one row per customer): `safe_to_spend_7d_eur`, `binding_limit`, `balance_limit_7d_eur`, `budget_limit_7d_eur`, `free_until_payday_eur`, `free_month_eur`, `balance_eur`, `balance_tx_id`, `bills_due_eur`, `essentials_reserve_eur`, `irregular_reserve_eur`, `cushion_eur`, `next_payday`, `days_to_payday`, `salary_status`, `income_month_eur`, `sweep_month_eur`, `committed_month_eur`, `essentials_month_eur`, `irregular_month_eur`, `usual_everyday_7d_eur`, `status`, `week_start`, `week_end`.

**Evidence.** Inputs: `balance_tx_id`; the recurring series of section 2; the basket rows of section 1 for the run-rates.

**Edge cases.**
- Payday tomorrow (N = 1): the balance limit spreads the free money over one day; the budget limit then usually binds.
- Salary late this month: `salary_status = late`, payday = last day of the month (conservative).
- Balance already below the reserves: `free_until_payday < 0` → 0, `nothing_free`.
- No regular income: payday assumed in 30 days, `salary_status = no_regular_income`, budget limit 0 (no income), so the result is 0. The coach should say it cannot estimate.
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

## 4. What-if savings — "How could I save more?"

An estimate (R13): "if the next months look like the average of the last 6 complete months, cutting X by p% saves …".

```
baseline_month = sum(out_eur) of the selection in the window, one-offs excluded / n_months
saving_month   = baseline_month * p / 100
saving_week    = saving_month * 7 / 30.4375
saving_year    = saving_month * 12
```

Selection (`app.whatif`): `category:<name>`, `mcc:<code>[,<code>…]`, `basket:<key>` or `merchant:<id>`; default `category:Restaurants`. Cut `app.whatif_pct`, default 20. Examples: dining out −20% = `category:Restaurants`; taxis −50% = `mcc:4121` with 50; all everyday spending −10% = `basket:everyday_spending` with 10.

**Output** (`04_what_if.sql`, one row per customer with spending in the selection): `selection`, `cut_pct`, `baseline_month_eur`, `saving_month_eur`, `saving_week_eur`, `saving_year_eur`, `n_tx`, `one_off_excluded_eur`, `n_one_off`, `n_months`, `period_start`, `period_end`. Method text for the card: "Average of your last 6 full months (one-off purchases left out), cut by p%".

**Evidence.** Rows of the selection in the window with `is_one_off = false`.

**Edge cases.** No spending in the selection: no row; the coach says there is nothing to cut. One-offs are reported in `one_off_excluded_eur` so the coach can mention them. Cutting essentials is allowed by the formula, but the coach should only suggest cuts to everyday spending (open question 5).

**Worked numbers** (dining out −20%):

| Customer | Restaurants / month | Saving / month | / week | / year | One-offs left out |
|---|---|---|---|---|---|
| CUST00001 | 56.86 (20 tx) | 11.37 | 2.62 | 136.45 | 0 |
| CUST00002 | 92.18 (33 tx) | 18.44 | 4.24 | 221.23 | 0 |
| CUST00006 | 15.56 (14 tx) | 3.11 | 0.72 | 37.33 | 0 |

## 5. Spender profile — "What kind of spender am I?"

Features over the window (all per month unless noted):
- `net_income` = (Salary + Other Income − Salary Sweep) / n_months
- `spend` = spend flow / n_months; `saving` = Invest Deposit / n_months
- `keep_rate` = (net_income − spend) / net_income, in % (investment deposits count as kept)
- basket shares of spend; `one_off_share` of spend
- `everyday_weekend_pct`: share of everyday spending on Saturday or Sunday
- `everyday_tx_month`, `everyday_avg_ticket_eur`, `top_everyday_category`
- `months_out_over_in`: months where spend + saving exceeded income − sweep
- `n_tx_below_zero`: transactions that left the balance below 0

**Primary label** (first rule that matches):

| Order | Key | Rule |
|---|---|---|
| 1 | `stretched` | keep_rate < 0 (spends more than comes in) |
| 2 | `big_ticket` | one_off_share ≥ 5% |
| 3 | `everyday_heavy` | everyday share ≥ 30% |
| 4 | `saver` | keep_rate ≥ 20% |
| 5 | `steady` | otherwise |

**Traits** (any number): `salary_moved_elsewhere` (sweep > 50% of income), `went_below_zero` (n_tx_below_zero > 0), `regular_investor` (saving > 0), `weekend_spender` (weekend share ≥ 45%; an even spread is 29%), `frequent_small_purchases` (≥ 12 everyday purchases a month).

The thresholds are fixed constants, set once from the sample's distribution (keep_rate p33 = 0.8%, p67 = 19.5%; everyday share p67 = 26.2%, p90 = 37.1%; one-off share p90 = 6.1%; weekend share p67 = 42.2%; everyday purchases a month p67 = 11.8). They do not depend on who is in the run. On the sample the labels split as stretched 29, steady 26, saver 24, everyday_heavy 12, big_ticket 8.

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
- Levels, most specific first: age band + area3 → age band + city → age band → all. The customer gets the first level with **at least 20 other peers** (`app.peer_min_n`). Small groups are never shown: this protects both statistics and privacy.
- Customers with a monthly Salary Sweep never enter a peer group (their spending happens elsewhere), and their own rows say `comparable = false`; the coach does not show those.
- Metrics (month averages over the window): total spend, the three baskets, and the categories Groceries, Restaurants, Transportation, Entertainment, Lifestyle, Travel, Home & Tech, Utilities, Housing. **Health is not benchmarked** (R9).
- `percentile` = share of the other peers in the group who spend less; `vs_median_pct` = you / peer median − 1.

**Output** (`06_peer_benchmark.sql`, one row per customer and metric): `you_month_eur`, `peer_median_month_eur`, `peer_p25_month_eur`, `peer_p75_month_eur`, `percentile`, `vs_median_pct`, `comparable`, `peer_level`, `peer_group`, `peer_n`, `period_start`, `period_end`.

**Evidence.** The customer's rows for the metric; the peer group definition and its n. Peer rows themselves are never exposed.

**Prototype scope.** Peers are the customers inside the range. With 99 customers almost every age × area cell is under 20, so the sample mostly falls back to age band or all. On the full population (5,100 customers; ~24 per age band × area3 cell on average) the area levels become usable. The full version reads the precomputed table of section 8. Statistics Finland's open Paavo data by postal code (median income, household size) could later refine "people like you"; it is not used here.

**Worked numbers** (sample range; numbers will change on the full population):

| Customer | Metric | You / month | Peer median | Percentile | Level (n) |
|---|---|---|---|---|---|
| CUST00001 | total spend | 2,087.92 | 2,787.20 | 23 | all (93) |
| CUST00001 | Restaurants | 56.86 | 177.01 | 14 | all (93) |
| CUST00002 | total spend | 1,702.17 | 3,285.49 | 10 | age band 45–54 (30) |
| CUST00002 | everyday spending | 430.29 | 778.19 | 17 | age band 45–54 (30) |
| CUST00006 | total spend | 253.54 | 2,730.33 | – (comparable = false) | 35–44 + Helsinki (21) |

## 7. Grocery store price index and switch saving

An estimate (R13) with a strong caveat: the data has **ticket totals, not item prices**. A store with a higher index means "people pay more per visit there than they pay elsewhere"; that mixes price level with basket size and store type.

**Model** (customer-normalised, two-way fixed effects): for grocery card purchases of the last 365 days,

```
ln(ticket) = a_customer + b_merchant + e
```

Fitted by alternating means (5 rounds, starting from b = 0) on customer × merchant cells with sufficient statistics `n, Σy, Σy²`. The customer effect removes "this person buys big baskets"; `b_merchant` is what remains. Effects are centred so that the visit-weighted average store is 0%.

- `index_pct = 100 × (exp(b) − 1)`; `se = σ / sqrt(n_visits)` with σ pooled from the residuals (degrees of freedom = visits − customers − merchants + 1); 95% interval shown.
- A store is shown only with 30+ visits. It is flagged as different from average only if |b| ≥ 3·se (with ~70 stores, 1.96·se would give about 3 false flags by chance).
- **Switch saving.** For each customer: the home store (largest grocery spend in the 365 days) against the lowest-index store of the **same MCC** that the customer already uses (3+ visits) and that has 30+ visits overall. `ticket_gap = 1 − exp(−(b_home − b_alt))`. Only if `b_home − b_alt ≥ 3 × sqrt(se_home² + se_alt²)`: `est_saving_month = home_spend_month × ticket_gap`, status `estimate`. Otherwise saving 0 and status `within_noise`, `already_lowest` or `no_alternative`.

**Output** (`07_store_price_index.sql`, two result sets). Per merchant: `merchant_id`, `mcc`, `n_visits`, `n_customers`, `avg_ticket_eur`, `index_pct`, `ci95_low_pct`, `ci95_high_pct`, `differs_from_average`, `shown`, `max_last_step` (convergence). Per customer: `home_merchant_id`, `home_index_pct`, `home_spend_month_eur`, `alt_merchant_id`, `alt_index_pct`, `ticket_gap_pct`, `ticket_gap_ci95_low_pct`, `status`, `est_saving_month_eur`, `period_start`, `period_end`.

**Evidence.** The customer's grocery transactions at the two stores; the index's method and n.

**What the sample shows (honest result).** 80 grocery merchants, 68 with 30+ visits. Index from −14.1% to +9.0% (SD 4.8 points), but the median 95% interval is ±10.0% (from ±3.1% for the busiest store to ±16.9%). **No store differs from average at |z| ≥ 3, and no customer gets a switch estimate**: on 99 customers the index is noise. The model converges (last step change 0.000000). On the full population a store gets about 51× more visits, so the interval shrinks about 7×, to roughly ±1.4% at the median, which is small enough to detect the −3.4% … +4.5% spread seen in the first full-data check. Until the full run confirms it, the coach must not present a store switch as a saving.

**Worked numbers** (sample range):

| Customer | Home store (index) | Home spend / month | Lowest-index alternative (index) | Status | Saving |
|---|---|---|---|---|---|
| CUST00001 | MRC-GRO-0032 (−1.4%) | 57.52 | MRC-GRO-0066 (−1.5%) | within_noise | 0 |
| CUST00002 | MRC-GRO-0032 (−1.4%) | 46.67 | MRC-GRO-0022 (−4.0%) | within_noise | 0 |
| CUST00006 | MRC-GRO-0036 (+3.0%) | 9.83 | none with 3+ visits | no_alternative | 0 |

Note that customers spread their grocery spend over many stores (15 to 74 different grocery merchants each over the two years, 56 on average), so even a real 3% gap at the home store is worth only a few euros a month.

## 8. Batched precompute for the full population (designed, not run)

The database has 2 GB RAM and 25 connections, and a full-table aggregate has restarted it before. Metrics 1–5 are per customer and run on demand for one customer (16–41 ms on the sample). Metrics 6 and 7 need everyone. They read small tables filled in batches of 100 customers, one connection, `statement_timeout = '60s'`, one batch at a time:

```sql
CREATE TABLE metric_customer_month (            -- input to the peer benchmark
    customer_id text, month date, metric text, value_eur numeric(12,2),
    PRIMARY KEY (customer_id, month, metric));
CREATE TABLE metric_grocery_cells (             -- input to the store index
    customer_id text, merchant_id text, mcc text,
    n int, sy double precision, syy double precision, spend_eur numeric(14,2),
    PRIMARY KEY (customer_id, merchant_id));
CREATE TABLE metric_peer_flags (customer_id text PRIMARY KEY, comparable boolean, age_band text, area3 text, city2 text);
```

```bash
# one batch per 100 customers: CUST00000-CUST00100, CUST00100-CUST00200, ... CUST05100-CUST05200
for i in $(seq 0 51); do
  from=$(printf 'CUST%05d' $((i*100))); to=$(printf 'CUST%05d' $((i*100+100)))
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
    -c "SET statement_timeout='60s'" \
    -c "SET app.customer_from='$from'" -c "SET app.customer_to='$to'" \
    -c "DELETE FROM metric_customer_month WHERE customer_id >= '$from' AND customer_id < '$to'" \
    -f core/metrics/precompute_customer_month.sql      # not written yet: the sums CTE of 06 as an INSERT
  sleep 1
done
```

Each batch reads about 70k rows through the `(customer_id, tx_at)` index (the sample batch takes under 1 s). The peer statistics then aggregate `metric_customer_month` (about 5,100 × 6 × 13 = 400k rows), and the store index iterates over `metric_grocery_cells` (about 5,100 × 56 = 285k cells) — both small and well inside the limits. Refresh once after each data load, not per request. Creating these tables needs the coordinator's go-ahead; this issue creates nothing.

## 9. How it was verified

Every file was run on the sample under `statement_timeout = '60s'` after rebasing onto `origin/main`, one connection at a time:

| File | Rows | Time |
|---|---|---|
| 01_recurring.sql | 315 | 0.65 s |
| 02_baskets.sql | 297 | 0.61 s |
| 03_safe_to_spend.sql | 99 | 1.32 s |
| 04_what_if.sql | 96 | 0.68 s |
| 05_spender_profile.sql | 99 | 2.36 s |
| 06_peer_benchmark.sql | 1,287 | 0.91 s |
| 07_store_price_index.sql | 80 + 99 | 0.25 s |

- `EXPLAIN` of every statement that reads `transactions` shows an `Index Scan` on `tx_customer_time` (07: `tx_customer_category`) with the customer range as the `Index Cond`; no `Seq Scan on transactions` anywhere.
- With `app.demo_today` set to 2026-09-14 and 2026-05-20 the window, statuses and results move as described in sections 2 and 3.
- The worked numbers above are copied from these runs.

## 10. Open questions for Renat

1. **Salary Sweep.** It is monthly for 5% of customers (the issue says yearly). Default: a transfer out of scope, excluded from peers. Is it "salary moved to another bank or account", or saving?
2. **Basket edge cases.** Defaults: Home & Tech → unexpected necessities; Travel → everyday spending; taxi → everyday spending; parking and fuel → regular essentials. Change any?
3. **Cushion** kept out of safe to spend: default 100 €. A fixed amount, or a share of monthly essentials?
4. **Investment deposits** are reserved as a commitment in safe to spend (they protect saving). Should the coach instead count them as free money?
5. **What-if scope.** Should the coach ever suggest cutting regular essentials (for example groceries), or only everyday spending?
6. **Store switch.** On the sample the index is noise. Do we show the store index in the demo only after the full-population precompute, or leave it out?
7. **Peer groups.** Minimum 20 peers. Is that acceptable for privacy, and do we want the Paavo income data?

## Rule references

R1 and R2: every number is a column with its period and an evidence filter (section 0). R5: the DEMO_TODAY bound in every query. R9: Health is summed only, never benchmarked or used in labels (sections 1, 5, 6). R13: safe to spend, what-if, peer benchmark and store index are estimates with a stated method and caveat (sections 3, 4, 6, 7).
