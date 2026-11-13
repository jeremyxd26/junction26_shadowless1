# Demo personas: selection and reference answers

Issue #22. Three customers from the synthetic dataset for the persona picker (`GET /api/personas`) and the 60-second demo. Each one makes every core demo question work. The numbers below come from the metric SQL in `core/metrics/` (definitions in `docs/design/metrics.md`) with `DEMO_TODAY = 2026-09-30`. They are the reference values for the eval set.

- Config: `core/config/personas.yaml`
- Selection: `core/config/select_personas.sql` (the per-customer checks) and `core/config/select_personas.py` (the driver: runs the checks and the metric files, picks the three, prints the reference answers)

## 1. The three personas

| | Marja (lead) | Eetu | Sanna |
|---|---|---|---|
| `customer_id` | CUST00493 | CUST00349 | CUST00860 |
| Age, band | 52, 45-54 | 32, 25-34 | 35, 35-44 |
| Postal area | Helsinki 00100 | Espoo 02140 | Helsinki 00590 |
| Role in the demo | mid-life, heavy regular essentials | young, high everyday spending | clear unexpected necessity in the last three months |
| Profile (05) | `steady` | `everyday_heavy` | `big_ticket` |
| Basket shares: regular / unexpected / everyday | **77.4%** / 6.8% / 15.7% | 58.5% / 11.3% / **30.1%** | 62.7% / **17.3%** / 19.9% |
| What stands out | rent 1,209.05 a month in central Helsinki | 736.87 a month of everyday spending, restaurants on top | Home & Tech purchase of 1,080.42 on 2026-09-28, 9× the usual one |

Display names are invented. The real `customer_id` stays the key.

## 2. Selection method

**Periods** (`DEMO_TODAY` = 2026-09-30):
- Last month: August 2026.
- Window: 2026-04-01 … 2026-09-30, the last 6 complete months of `metrics.md` section 0. Every average, the what-if baseline and the recurring rule use it.
- "Last 6 months" for dining out has two readings: the window (Apr–Sep), or the 6 months before the month in progress (Mar–Aug). The script counts dining months in both and keeps the smaller count (`dining_months_of_6`), so a persona passes under either reading.
- Last three months: 2026-07-01 … 2026-09-30.

**Checks.** The persona-level checks come from issue #22; the lead/relaxed split was set by the coordinator. The marked rows are extra demo-quality checks.

| Check | Lead persona | Other two | Source |
|---|---|---|---|
| Taxi rides (MCC 4121) in August 2026 | ≥ 3 | ≥ 1 | `select_personas.sql` |
| Months with dining out (MCC 5812/5813/5814) | 6 of 6 | ≥ 5 of 6 | `select_personas.sql` |
| Salary detected as recurring (incoming) | yes | yes | `01_recurring.sql` |
| Housing payment detected as recurring | yes | yes | `01_recurring.sql` |
| *Housing paid in all 6 window months and in September* | yes | yes | `select_personas.sql` (so safe to spend never shows a skipped rent) |
| *Salary received this month* | yes | yes | `03_safe_to_spend.sql`, `salary_status` |
| *No Salary Sweep in the window* | yes | yes | `select_personas.sql` (a sweep customer is excluded from peer groups) |
| Safe to spend on `DEMO_TODAY` | > 0 | > 0 | `03_safe_to_spend.sql` |
| Peer group: other customers in the same age band + area3 cell | ≥ 20 | ≥ 20 | `customers` table (metrics.md section 6, most specific level) |

**Slots and ranking.** A candidate that passes can fill these slots:
- `young_everyday`: age ≤ 34, scored by everyday share.
- `midlife_essentials`: age 35–54, scored by regular-essentials share.
- `recent_unexpected`: in the last three months, a Home & Tech purchase, or a one-off Groceries or Transportation purchase (not taxi), of at least 300 € that is a one-off by the metrics rule or at least 3× the customer's median in that category. Scored by its amount. Health is left out (R9: a persona story never rests on health spending).

Within a slot the ranking is: safe-to-spend status `ok` first, then the score, then more taxi rides. The lead (every check at the lead level) takes its slot first. The other two slots are filled from all passing candidates, the slot with fewer candidates first, and a different age band is preferred so that the three look different.

**Scan within the database limits.** One connection and `statement_timeout = '60s'`. Customer ranges of 100, at most 2,000 customers. Nothing is created, and no statement aggregates the whole `transactions` table.
1. For each range, a taxi pre-filter on the `(customer_id, mcc, tx_date)` index finds customers with a taxi ride in August.
2. For each of those customers alone (`[id, next id)`), `select_personas.sql` runs. If its cheap checks pass, `03`, `01` and `05` follow. Metrics 1 to 5 depend only on the customer's own rows, so a one-customer run equals a range run (metrics.md section 0).
3. The scan stops after a range once there are 3 lead candidates, a full set of three, and 3 candidates in every slot.

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
failed checks among the customers with a taxi ride: {'dining<5_of_6': 144, 'housing_not_every_month': 41, 'peer_area3<20': 31, 'safe_to_spend<=0': 10, 'salary_sweep': 1}

chosen:
  midlife_essentials   CUST00493  lead  age 52  00100  steady  (lead)
  young_everyday       CUST00349  other age 32  02140  everyday_heavy
  recent_unexpected    CUST00860  other age 35  00590  big_ticket
-- 605 queries, 397.6 s in the database, 433.3 s total
```

The same run before the metrics merge (branch `r/6-metrics-design`) chose the same three in 239 s. The run above was slower because the shared database was busy with other sessions at the time; a single one-customer query takes 0.02–0.05 s on an idle database. No query timed out.

The yield explains the relaxed rule for the other two personas: only about 1 customer in 300 meets every check at the lead level (3 of the 900 screened). Under 35s are rare among the candidates (11 of 78). None of the 18–24 year olds passes with status `ok`.

**Shortlists** (top of each slot; the chosen persona first):

| Slot | Candidates (age, profile, score, safe to spend 7d, status) |
|---|---|
| lead (every check) | **CUST00493** (52, steady, essentials 77.4%, 175.46 ok); CUST00848 (52, saver, 63.0%, 423.94 ok); CUST00151 (42, stretched, 61.0%, 91.83 below_usual) |
| young_everyday | **CUST00349** (32, everyday_heavy, 30.1%, 285.21 ok); CUST00849 (25, steady, 28.0%, 166.84 ok); CUST00305 (31, steady, 26.2%, 92.03 ok) |
| recent_unexpected | **CUST00860** (35, big_ticket, 1,080.42, 180.26 ok); CUST00183 (40, everyday_heavy, 785.80, 281.65 ok); CUST00857 (37, steady, 655.93, 335.46 ok) |

## 3. Checks with the numbers

| Check | CUST00493 Marja (lead) | CUST00349 Eetu | CUST00860 Sanna |
|---|---|---|---|
| Taxi rides in August 2026 | **3** (135.08 €) | 1 (63.62 €) | 1 (52.84 €) |
| Dining months, Apr–Sep / Mar–Aug | 6 / 6 | 6 / 6 | 6 / 6 |
| Salary series (01) | in, 6 of 6 months, 2,571.73 / month, day 15, done this month (arrived 2026-09-28) | in, 6 of 6, 3,171.65, day 15, done this month | in, 6 of 6, 3,187.25, day 15, done this month |
| Housing series (01) | 6 of 6, 1,209.05 / month, day 3, done this month (2026-09-08) | 6 of 6, 683.77, day 3, done this month | 6 of 6, 836.65, day 3, done this month |
| Salary Sweep months | 0 | 0 | 0 |
| Safe to spend 7d (03) | **175.46**, ok | **285.21**, ok | **180.26**, ok |
| Peer cell (age band + area3) | 45-54 / 001 | 25-34 / 021 | 35-44 / 005 |
| Other customers in the cell (`customers`) | 127 | 24 | 123 |
| Other comparable customers (`metric_peer_flags`, sweepers removed) | 121 | 24 | 118 |
| Largest unexpected necessity Jul–Sep (Health excluded) | Home & Tech 104.41 (2.5× median) | Home & Tech 98.98 (1.6×) | **Home & Tech 1,080.42 on 2026-09-28, 9.0× median, one-off** (tx 606016) |

Eetu's cell (25-34 in 021xx, Espoo) has exactly 24 other comparable customers, enough for the 20-peer rule with a small margin. All three are `comparable = true` in `metric_peer_flags`.

## 4. Reference answers (eval set)

All answers: `DEMO_TODAY` 2026-09-30, window 2026-04-01 … 2026-09-30 (`n_months` = 6). Amounts are euros.

### Q1. "Where did my money go?" — three baskets (`02_baskets.sql`, month averages)

| Persona | Regular essentials | Unexpected necessities | Everyday spending |
|---|---|---|---|
| CUST00493 | 1,645.05 (77.4%) | 144.60 (6.8%) | 334.44 (15.7%) |
| CUST00349 | 1,431.19 (58.5%) | 277.45 (11.3%); 214.41 without one 378.22 one-off | 736.87 (30.1%); 694.73 without one 252.86 one-off |
| CUST00860 | 1,889.04 (62.7%) | 521.15 (17.3%); 341.08 without one 1,080.42 one-off | 600.41 (19.9%) |

### Q2. "How much did I spend on taxis last month?" — MCC 4121, 2026-08-01 … 2026-08-31

| Persona | Rides | Total |
|---|---|---|
| CUST00493 | 3 | 135.08 |
| CUST00349 | 1 | 63.62 |
| CUST00860 | 1 | 52.84 |

### Q3. "What can I safely spend this week?" — `03_safe_to_spend.sql`, week 2026-10-01 … 2026-10-07, payday 2026-10-15 (N = 15)

| | CUST00493 | CUST00349 | CUST00860 |
|---|---|---|---|
| **Safe to spend 7d** | **175.46** (budget limit), ok | **285.21** (budget limit), ok | **180.26** (budget limit), ok |
| Budget: income − committed − essentials − irregular per month | 2,571.73 − 1,374.89 − 289.62 − 144.30 = 762.92 | 3,171.65 − 1,069.73 − 584.87 − 276.88 = 1,240.17 | 3,187.25 − 1,023.04 − 860.34 − 520.08 = 783.79 |
| Committed (recurring out) | housing 1,209.05 + utilities 165.85 | housing 683.77 + investment 242.95 + utilities 143.01 | housing 836.65 + utilities 186.40 |
| Balance limit 7d | 4,265.71 (balance 10,745.42, bills due 1,290.78) | 10,747.98 (balance 24,310.32, bills due 754.25) | 5,864.86 (balance 14,276.35, bills due 928.50) |
| Usual everyday spending / 7 days | 76.76 | 159.45 | 137.80 |

The budget limit binds for all three: the balances are large, so the estimate is driven by the typical month (`free_month × 7 / 30.4375`).

### Q4. "How much could I save if I reduced dining out by 20%?" — `04_what_if.sql`, `app.whatif = mcc:5812,5813,5814`, `app.whatif_pct = 20`

| Persona | Baseline / month | Saving / month | / week | / year | Transactions | One-offs left out | Status |
|---|---|---|---|---|---|---|---|
| CUST00493 | 100.52 | **20.10** | 4.62 | 241.26 | 59 | 0 | estimate |
| CUST00349 | 293.08 | **58.62** | 13.48 | 703.39 | 59 | 0 | estimate |
| CUST00860 | 229.56 | **45.91** | 10.56 | 550.95 | 60 | 0 | estimate |

With `category:Restaurants` instead, the baseline is 102.66 for CUST00493 and 294.73 for CUST00349. Each of them has one restaurant payment without a card merchant or MCC (tx 342690, 12.81 €, and tx 242240, 9.92 €), which the MCC selection does not see. CUST00860 is the same both ways. The reference uses the MCC selection, as the demo question defines it.

### Q5. "What kind of spender am I?" — `05_spender_profile.sql`, plus the peer comparison

| Persona | Profile | Why (first matching rule) | Traits | Keep rate | Net income / month | Spend / month |
|---|---|---|---|---|---|---|
| CUST00493 | `steady` | keep rate 17.6% < 20, everyday share 15.7% < 30, one-off share 0% | frequent_small_purchases | 17.6% | 2,577.84 | 2,124.09 |
| CUST00349 | `everyday_heavy` | one-off share 4.3% < 5, everyday share 30.1% ≥ 30 (checked before saver) | regular_investor, frequent_small_purchases | 22.6% | 3,161.55 | 2,445.52 |
| CUST00860 | `big_ticket` | keep rate 15.4% ≥ 0, one-off share 6.0% ≥ 5 | frequent_small_purchases | 15.4% | 3,558.38 | 3,010.59 |

**Peer comparison: pending.** The values come from `06_peer_benchmark.sql` once it reads the precomputed marts (issue #21). They will be filled in with a small follow-up. Peer groups, at level `age_band+area3`:

| Persona | Peer group | Comparable others |
|---|---|---|
| CUST00493 | 45-54, 001xx | 121 |
| CUST00349 | 25-34, 021xx | 24 |
| CUST00860 | 35-44, 005xx | 118 |

## 5. Direct checks against `transactions`

For each persona, single-customer queries on `transactions` (in `select_personas.py`, `--answers`) give the same values as the tables above:

| Persona | Taxi Aug 2026 (n, €) | Dining in the window (n, €) | Dining baseline = € / 6 | By month, Mar … Sep (€) |
|---|---|---|---|---|
| CUST00493 | 3, 135.08 | 59, 603.14 | 100.52 | 169.21, 135.38, 187.70, 55.98, 134.83, 25.91, 63.34 |
| CUST00349 | 1, 63.62 | 59, 1,758.48 | 293.08 | 175.49, 418.74, 169.48, 317.61, 279.08, 506.19, 67.38 |
| CUST00860 | 1, 52.84 | 60, 1,377.38 | 229.56 | 192.52, 172.89, 309.04, 353.62, 178.68, 138.94, 224.21 |

None of the three has a dining one-off in the window, so the plain sum divided by 6 equals the what-if baseline.

## 6. Reproduce

```
python core/config/select_personas.py                     # screen and choose (stops by itself, at most 2,000 customers)
python core/config/select_personas.py --answers CUST00493,CUST00349,CUST00860
```

`--today` changes `DEMO_TODAY`, and `--out file.json` writes every value. The reference answers change if the data is reloaded or a metric definition changes. Rerun `--answers` and update this document in that case.
