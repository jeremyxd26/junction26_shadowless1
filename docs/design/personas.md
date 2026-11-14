# Demo personas: selection and reference answers

Issue #22. Four customers from the synthetic dataset for the persona picker (`GET /api/personas`) and the 60-second demo. Each one gives non-trivial answers to the four questions of the challenge brief. The numbers below come from the metric SQL in `core/metrics/` (definitions in `docs/design/metrics.md`) with `DEMO_TODAY = 2026-09-30`. They are the reference values for the eval set (#40).

- Config: `core/config/personas.yaml`
- Selection: `core/config/select_personas.sql` (the per-customer checks) and `core/config/select_personas.py` (the driver: runs the checks and the metric files, and with `--answers` prints the reference answers)

## 1. The four personas

| | Sanna (lead) | Marja | Eetu | Aleksi |
|---|---|---|---|---|
| `customer_id` | CUST00860 | CUST00493 | CUST00349 | CUST00849 |
| Age, band | 35, 35-44 | 52, 45-54 | 32, 25-34 | 25, 25-34 |
| Postal area | Helsinki 00590 | Helsinki 00100 | Espoo 02140 | Espoo 02250 |
| Role in the demo | clear unexpected necessity in the last 30 days | mid-life, heavy regular essentials | high everyday spending | young adult, tight budget |
| Profile (05) | `big_ticket` | `steady` | `everyday_heavy` | `steady` |
| Basket shares: regular / unexpected / everyday | 62.7% / **17.3%** / 19.9% | **77.4%** / 6.8% / 15.7% | 58.5% / 11.3% / **30.1%** | 65.4% / 6.6% / 28.0% |
| What the data shows | Home & Tech purchase of 1,080.42 on 2026-09-28, 9× the usual one | housing is 56.7% of spending (1,209.05 a month); restaurants every month | 736.87 a month of everyday spending, restaurants on top | keep rate 9.4%; 20 transactions left the balance below zero since April |

Display names are invented. The real `customer_id` stays the key.

## 2. Selection method

**Periods** (`DEMO_TODAY` = 2026-09-30):
- Last month: August 2026.
- Window: 2026-04-01 … 2026-09-30, the last 6 complete months of `metrics.md` section 0. Every average, the what-if baseline and the recurring rule use it.
- "Last 6 months" for dining out has two readings: the window (Apr–Sep), or the 6 months before the month in progress (Mar–Aug). The screening counts both and keeps the smaller count (`dining_months_of_6`).
- Last three months: 2026-07-01 … 2026-09-30.

### 2.1 The scan, as run

The scan used the checks of issue #22 at the time. The lead/relaxed split was set by the coordinator. The marked rows are extra demo-quality checks.

| Check | Lead tier | Other tier | Source |
|---|---|---|---|
| Taxi rides (MCC 4121) in August 2026 | ≥ 3 | ≥ 1 | `select_personas.sql` |
| Months with card dining (MCC 5812/5813/5814) | 6 of 6 | ≥ 5 of 6 | `select_personas.sql` |
| Salary detected as recurring (incoming) | yes | yes | `01_recurring.sql` |
| Housing payment detected as recurring | yes | yes | `01_recurring.sql` |
| *Housing paid in all 6 window months and in September* | yes | yes | `select_personas.sql` (so safe to spend never shows a skipped housing payment) |
| *Salary received this month* | yes | yes | `03_safe_to_spend.sql`, `salary_status` |
| *No Salary Sweep in the window* | yes | yes | `select_personas.sql` (a sweep customer is excluded from peer groups) |
| Safe to spend on `DEMO_TODAY` | > 0 | > 0 | `03_safe_to_spend.sql` |
| Peer group: other customers in the same age band + area3 cell | ≥ 20 | ≥ 20 | `customers` table (metrics.md section 6, most specific level) |

**Slots and ranking.** A candidate that passes can fill these slots:
- `young_everyday`: age ≤ 34, scored by everyday share.
- `midlife_essentials`: age 35–54, scored by regular-essentials share.
- `recent_unexpected`: in the last three months, a Home & Tech purchase, or a one-off Groceries or Transportation purchase (not taxi), of at least 300 € that is a one-off by the metrics rule or at least 3× the customer's median in that category. Scored by its amount. Health is left out (R9: a persona story never rests on health spending).

Within a slot the ranking is: safe-to-spend status `ok` first, then the score, then more taxi rides. The script's lead tier takes its slot first. The other two slots are filled from all passing candidates, the slot with fewer candidates first, and a different age band is preferred so that the personas look different.

**Scan within the database limits.** One connection and `statement_timeout = '60s'`. Customer ranges of 100, at most 2,000 customers. Nothing is created, and no statement aggregates the whole `transactions` table.
1. For each range, a taxi pre-filter on the `(customer_id, mcc, tx_date)` index finds customers with a taxi ride in August.
2. For each of those customers alone (`[id, next id)`), `select_personas.sql` runs. If its cheap checks pass, `03`, `01` and `05` follow. Metrics 1 to 5 depend only on the customer's own rows, so a one-customer run equals a range run (metrics.md section 0).
3. The scan stops after a range once there are 3 lead-tier candidates, a full set of three, and 3 candidates in every slot.

**Run** (2026-11-13, merged metric files of `origin/main` 3a91570):

```
$ python core/config/select_personas.py
CUST00000..CUST00100  taxi 26  pass  6  lead  0  slots {'young_everyday': 0, 'midlife_essentials': 6, 'recent_unexpected': 1}  33.79 s
CUST00100..CUST00200  taxi 23  pass 10  lead  1  slots {'young_everyday': 1, 'midlife_essentials': 15, 'recent_unexpected': 4}  41.51 s
CUST00200..CUST00300  taxi 35  pass  4  lead  1  slots {'young_everyday': 1, 'midlife_essentials': 19, 'recent_unexpected': 4}  36.95 s
CUST00300..CUST00400  taxi 28  pass  6  lead  1  slots {'young_everyday': 4, 'midlife_essentials': 22, 'recent_unexpected': 5}  19.77 s
CUST00400..CUST00500  taxi 36  pass 12  lead  2  slots {'young_everyday': 7, 'midlife_essentials': 31, 'recent_unexpected': 5}  32.79 s
CUST00500..CUST00600  taxi 27  pass 12  lead  2  slots {'young_everyday': 8, 'midlife_essentials': 42, 'recent_unexpected': 6}  108.72 s
CUST00600..CUST00700  taxi 29  pass 10  lead  2  slots {'young_everyday': 8, 'midlife_essentials': 52, 'recent_unexpected': 11}  74.23 s
CUST00700..CUST00800  taxi 22  pass  5  lead  2  slots {'young_everyday': 8, 'midlife_essentials': 57, 'recent_unexpected': 12}  20.53 s
CUST00800..CUST00900  taxi 31  pass 13  lead  3  slots {'young_everyday': 11, 'midlife_essentials': 67, 'recent_unexpected': 16}  60.99 s

screened 9 ranges (CUST00000..CUST00900), 257 with a taxi ride last month, 78 pass every check (3 as lead)
[table of the 78 passing candidates omitted here; the full output is in PR #38]
failed checks among the customers with a taxi ride: {'dining<5_of_6': 144, 'housing_not_every_month': 41, 'peer_area3<20': 31, 'safe_to_spend<=0': 10, 'salary_sweep': 1}

chosen:
  midlife_essentials   CUST00493  lead  age 52  00100  steady  (lead)
  young_everyday       CUST00349  other age 32  02140  everyday_heavy
  recent_unexpected    CUST00860  other age 35  00590  big_ticket
-- 605 queries, 397.6 s in the database, 433.3 s total
```

The same run before the metrics merge chose the same three in 239 s. The run above was slower because the shared database was busy with other sessions at the time. No query timed out.

### 2.2 Product decision after the scan

The owner changed the set after the scan (comments on #22 and #40):
- **Taxi is no longer a selection criterion or a demo anchor.** Only about 3% of customers take 3 or more taxis in a month. The taxi numbers stay below as ordinary reference values. The criterion that replaces it: every persona answers the four questions of the challenge brief with non-trivial numbers, and the lead has an unexpected necessity in the last 30 days.
- **The lead is Sanna (CUST00860).** Hers is the clearest recent unexpected necessity: the 1,080.42 Home & Tech purchase on 2026-09-28. The script's lead tier picked CUST00493 by the taxi rule, so it no longer decides the lead.
- **A fourth persona, Aleksi (CUST00849, age 25), is added** because young adults are the bank's focus. CUST00849 was the runner-up of the `young_everyday` slot (everyday share 28.0%, status `ok`). The checks and reference answers below come from the same per-customer runs. CUST00849 has 1 taxi ride in August, and card dining in 6 of the 6 window months but in 5 of the 6 months from March to August (none in March).

**Shortlists** of the scan (top of each slot; the chosen persona first):

| Slot | Candidates (age, profile, score, safe to spend 7d, status) |
|---|---|
| lead tier (every check) | CUST00493 (52, steady, essentials 77.4%, 78.86 ok); CUST00848 (52, saver, 63.0%, 233.06 ok); CUST00151 (42, stretched, 61.0%, 91.83 below_usual) |
| young_everyday | **CUST00349** (32, everyday_heavy, 30.1%, 147.23 below_usual); **CUST00849** (25, steady, 28.0%, 123.15 ok); CUST00305 (31, steady, 26.2%, 92.03 ok) |
| recent_unexpected | **CUST00860** (35, big_ticket, 1,080.42, 97.46 below_usual); CUST00183 (40, everyday_heavy, 785.80, 240.25 ok); CUST00857 (37, steady, 655.93, 153.77 below_usual) |

Safe to spend 7d and its status are after the savings goal of #391 (as_of 2026-09-30, rule state, no review answered), recomputed per customer with `get_safe_to_spend`. The scan itself ran before #391 and chose on its earlier figures, when all four personas were `ok`; the goal moved several of them to `below_usual`, which the persona choice does not depend on.

Only one of the 78 passing candidates is 18–24 (CUST00164, age 23), and its safe-to-spend status is `below_usual`. Among the passing candidates with status `ok`, Aleksi (25) is the youngest.

## 3. Checks with the numbers

| Check | CUST00860 Sanna (lead) | CUST00493 Marja | CUST00349 Eetu | CUST00849 Aleksi |
|---|---|---|---|---|
| Salary series (01) | in, 6 of 6 months, 3,187.25 / month, day 15, done this month | in, 6 of 6, 2,571.73, day 15, done this month (arrived 2026-09-28) | in, 6 of 6, 3,171.65, day 15, done this month | in, 6 of 6, 2,088.35, day 15, done this month |
| Housing series (01) | 6 of 6, 836.65 / month, day 3, done this month | 6 of 6, 1,209.05, day 3, done this month (2026-09-08) | 6 of 6, 683.77, day 3, done this month | 6 of 6, 613.93, day 6, done this month |
| Salary Sweep months | 0 | 0 | 0 | 0 |
| Safe to spend 7d (03), after the savings goal (#391) | **97.46**, below usual (goal 360) | **78.86**, ok (goal 420) | **147.23**, below usual (goal 600) | **123.15**, ok (goal 190) |
| Unexpected necessity Jul–Sep, largest (Health excluded) | **Home & Tech 1,080.42 on 2026-09-28, 9.0× median, one-off** (tx 606016) | Home & Tech 104.41 (2.5× median) | Home & Tech 98.98 (1.6×) | none |
| Months with restaurant spending (category), Mar–Sep | 7 of 7 | 7 of 7 | 7 of 7 | 6 of 7 (none in March) |
| Peer cell (age band + area3) | 35-44 / 005 | 45-54 / 001 | 25-34 / 021 | 25-34 / 022 |
| Other customers in the cell (`customers`) | 123 | 127 | 24 | 40 |
| Other comparable customers (`metric_peer_flags`, sweepers removed) | 118 | 121 | 24 | 39 |

Eetu's cell (25-34 in 021xx, Espoo) has exactly 24 other comparable customers, enough for the 20-peer rule with a small margin. All four are `comparable = true` in `metric_peer_flags`.

The scan checks the cell size on `customers`. The comparable counts (and `peer_group.comparable_others` in `personas.yaml`) come from the mart of issue #21. `select_personas.py --answers` prints them as `peer_n` of `06_peer_benchmark.sql`. Subtract 1 for the persona itself:

```sql
SELECT age_band, area3, count(*) AS members, count(*) FILTER (WHERE comparable) AS comparable
FROM metric_peer_flags
WHERE (age_band, area3) IN (('35-44', '005'), ('45-54', '001'), ('25-34', '021'), ('25-34', '022'))
GROUP BY 1, 2;
-- 25-34 021: 25 members, 25 comparable;  25-34 022: 41, 40;  35-44 005: 124, 119;  45-54 001: 128, 122   (as_of 2026-09-30)
```

## 4. Reference answers (eval set)

All answers: `DEMO_TODAY` 2026-09-30, window 2026-04-01 … 2026-09-30 (`n_months` = 6). Amounts are euros. Q1 to Q4 are the four questions of the challenge brief.

### Q1. "Where did my money go?" — three baskets (`02_baskets.sql`, month averages)

| Persona | Regular essentials | Unexpected necessities | Everyday spending |
|---|---|---|---|
| CUST00860 | 1,889.04 (62.7%) | 521.15 (17.3%); 341.08 without one 1,080.42 one-off | 600.41 (19.9%) |
| CUST00493 | 1,645.05 (77.4%) | 144.60 (6.8%) | 334.44 (15.7%) |
| CUST00349 | 1,431.19 (58.5%) | 277.45 (11.3%); 214.41 without one 378.22 one-off | 736.87 (30.1%); 694.73 without one 252.86 one-off |
| CUST00849 | 1,229.97 (65.4%) | 124.49 (6.6%) | 526.60 (28.0%) |

### Q2. "What kind of spender am I?" — `05_spender_profile.sql`, plus the peer comparison

| Persona | Profile | Why (first matching rule) | Traits | Keep rate | Net income / month | Spend / month |
|---|---|---|---|---|---|---|
| CUST00860 | `big_ticket` | keep rate 15.4% ≥ 0, one-off share 6.0% ≥ 5 | frequent_small_purchases | 15.4% | 3,558.38 | 3,010.59 |
| CUST00493 | `steady` | keep rate 17.6% < 20, everyday share 15.7% < 30, one-off share 0% | frequent_small_purchases | 17.6% | 2,577.84 | 2,124.09 |
| CUST00349 | `everyday_heavy` | one-off share 4.3% < 5, everyday share 30.1% ≥ 30 (checked before saver) | regular_investor, frequent_small_purchases | 22.6% | 3,161.55 | 2,445.52 |
| CUST00849 | `steady` | keep rate 9.4% < 20, everyday share 28.0% < 30, one-off share 0% | went_below_zero (20 transactions), frequent_small_purchases | 9.4% | 2,075.65 | 1,881.06 |

Sanna's spike review (#68) changes the shares, not the profile. Each share is of all spending (#235). The values below are one-off share / everyday share / unexpected share in %, and the profile is `big_ticket` in every state:

| No review | Pending | "Needed" | "My choice" |
|---|---|---|---|
| 6.0 / 19.9 / 17.3 | 6.0 / 19.9 / 11.3 | 6.0 / 19.9 / 17.3 | 6.0 / 25.9 / 11.3 |

**Peer comparison** ("people of the same age and area"). `06_peer_benchmark.sql` is run for each persona alone; it reads the marts built by `core/marts/build.py` (`peer_source = marts`). Level `age_band+area3`, `shown = true` for all four. Month averages over the window. The percentile is the share of the other peers in the group who spend less.

| Persona | Peer group (comparable others) | Metric | You | Peer median | p25 – p75 | Percentile | vs median |
|---|---|---|---|---|---|---|---|
| CUST00860 | 35-44, 005xx (118) | total spending | 3,010.59 | 2,975.65 | 2,313.00 – 3,713.90 | 51 | +1.2% |
| | | regular essentials | 1,889.04 | 1,976.48 | 1,613.18 – 2,308.72 | 43 | −4.4% |
| | | unexpected necessities | 521.15 | 299.03 | 139.36 – 468.85 | 87 | +74.3% |
| | | everyday spending | 600.41 | 727.85 | 445.69 – 1,038.40 | 39 | −17.5% |
| CUST00493 | 45-54, 001xx (121) | total spending | 2,124.09 | 3,567.81 | 2,774.64 – 4,731.34 | 8 | −40.5% |
| | | regular essentials | 1,645.05 | 2,221.92 | 1,911.78 – 2,752.60 | 13 | −26.0% |
| | | unexpected necessities | 144.60 | 363.64 | 189.84 – 618.87 | 14 | −60.2% |
| | | everyday spending | 334.44 | 913.24 | 547.71 – 1,454.59 | 8 | −63.4% |
| CUST00349 | 25-34, 021xx (24) | total spending | 2,445.52 | 1,894.55 | 1,664.60 – 2,790.60 | 67 | +29.1% |
| | | regular essentials | 1,431.19 | 1,365.34 | 1,143.86 – 2,090.07 | 58 | +4.8% |
| | | unexpected necessities | 277.45 | 165.26 | 85.26 – 277.45 | 75 | +67.9% |
| | | everyday spending | 736.87 | 479.25 | 270.63 – 736.87 | 75 | +53.8% |
| CUST00849 | 25-34, 022xx (39) | total spending | 1,881.06 | 2,202.21 | 1,819.64 – 2,811.44 | 31 | −14.6% |
| | | regular essentials | 1,229.97 | 1,537.60 | 1,188.80 – 1,943.43 | 28 | −20.0% |
| | | unexpected necessities | 124.49 | 205.58 | 104.51 – 334.20 | 36 | −39.4% |
| | | everyday spending | 526.60 | 538.51 | 392.92 – 691.95 | 46 | −2.2% |

`06` also returns the category metrics (Groceries, Restaurants, Transportation, Entertainment, Lifestyle, Travel, Home & Tech, Utilities, Housing; never Health). Each persona's group size equals the comparable count from `metric_peer_flags` in section 3. For Eetu, the upper quartile of two metrics equals Eetu's own value: the group statistics include the persona, and the group is small (25 with the persona).

### Q3. "What can I safely spend this week?" — `03_safe_to_spend.sql`, week 2026-10-01 … 2026-10-07, payday 2026-10-15 (N = 15)

| | CUST00860 | CUST00493 | CUST00349 | CUST00849 |
|---|---|---|---|---|
| **Safe to spend 7d** (after the savings goal, #391) | **97.46** (budget limit), below usual | **78.86** (budget limit), ok | **147.23** (budget limit), below usual | **123.15** (budget limit), ok |
| Savings goal (#391): safe to save before the review's answer, rounded down to 10 € | 360 | 420 | 600 | 190 |
| Budget: income − committed − essentials − irregular per month | 3,187.25 − 1,023.04 − 860.34 − 520.08 = 783.79 | 2,571.73 − 1,374.89 − 289.62 − 144.30 = 762.92 | 3,171.65 − 1,069.73 − 584.87 − 276.88 = 1,240.17 | 2,088.35 − 712.67 − 525.97 − 124.23 = 725.47 |
| Committed (recurring out) | housing 836.65 + utilities 186.40 | housing 1,209.05 + utilities 165.85 | housing 683.77 + investment 242.95 + utilities 143.01 | housing 613.93 + utilities 98.74 |
| Balance limit 7d | 5,864.86 (balance 14,276.35, bills due 928.50) | 4,265.71 (balance 10,745.42, bills due 1,290.78) | 10,747.98 (balance 24,310.32, bills due 754.25) | 382.49 (balance 1,902.64, bills due 662.59) |
| Usual everyday spending / 7 days | 137.80 | 76.76 | 159.45 | 120.86 |

The budget limit binds for all four: the estimate is driven by the typical month after the savings goal (`(free_month − goal) × 7 / 30.4375`, #391). Aleksi's balance limit (382.49) is the closest to binding. Each column of the SQL is rounded on its own, so a sum written out here can differ from the result by 0.01 (Aleksi: 725.48 against 725.47).

### Q4. "How much could I save if I reduced dining out by 20%?" — `04_what_if.sql`, `app.whatif = category:Restaurants`, `app.whatif_pct = 20`

"Dining out" is the category Restaurants (team decision): it includes restaurant payments without a card MCC. The MCC group 5812/5813/5814 covers card payments only.

| Persona | Baseline / month | Saving / month | / week | / year | Transactions | One-offs left out | Status | Card payments only (MCC): baseline |
|---|---|---|---|---|---|---|---|---|
| CUST00860 | 229.56 | **45.91** | 10.56 | 550.95 | 60 | 0 | estimate | 229.56 (same) |
| CUST00493 | 102.66 | **20.53** | 4.72 | 246.38 | 60 | 0 | estimate | 100.52 (1 payment without MCC: tx 342690, 12.81) |
| CUST00349 | 294.73 | **58.95** | 13.56 | 707.36 | 60 | 0 | estimate | 293.08 (1 without MCC: tx 242240, 9.92) |
| CUST00849 | 277.48 | **55.50** | 12.76 | 665.96 | 55 | 0 | estimate | 274.07 (1 without MCC, 20.45) |

### Other reference values: taxi rides last month (MCC 4121, 2026-08-01 … 2026-08-31)

Not a selection criterion and not a demo anchor (section 2.2), but an ordinary MCC-group question:

| Persona | Rides | Total |
|---|---|---|
| CUST00860 | 1 | 52.84 |
| CUST00493 | 3 | 135.08 |
| CUST00349 | 1 | 63.62 |
| CUST00849 | 1 | 31.98 |

## 5. Direct checks against `transactions`

For each persona, single-customer queries on `transactions` (in `select_personas.py`, `--answers`) give the same values as the tables above:

| Persona | Taxi Aug 2026 (n, €) | Restaurants in the window (n, €) | Dining baseline = € / 6 | Restaurants by month, Mar … Sep (€) |
|---|---|---|---|---|
| CUST00860 | 1, 52.84 | 60, 1,377.38 | 229.56 | 226.53, 172.89, 309.04, 353.62, 178.68, 138.94, 224.21 |
| CUST00493 | 3, 135.08 | 60, 615.95 | 102.66 | 169.21, 135.38, 187.70, 55.98, 147.64, 25.91, 63.34 |
| CUST00349 | 1, 63.62 | 60, 1,768.40 | 294.73 | 175.49, 418.74, 169.48, 317.61, 279.08, 506.19, 77.30 |
| CUST00849 | 1, 31.98 | 55, 1,664.89 | 277.48 | none, 240.78, 200.42, 121.69, 547.93, 238.84, 315.23 |

None of the four has a restaurant one-off in the window, so the plain sum divided by 6 equals the what-if baseline.

## 6. Reproduce

```
python core/config/select_personas.py                     # the scan (stops by itself, at most 2,000 customers)
python core/config/select_personas.py --answers CUST00860,CUST00493,CUST00349,CUST00849
```

`--today` changes `DEMO_TODAY`, and `--out file.json` writes every value. The reference answers change if the data is reloaded or a metric definition changes. Rerun `--answers` and update this document in that case.
