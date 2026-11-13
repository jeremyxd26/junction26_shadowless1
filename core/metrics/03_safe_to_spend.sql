-- Metric 3: safe to spend this week (the 7 days after DEMO_TODAY).  Definition: docs/design/metrics.md, section 3.
--
-- Inputs (session settings, all optional):
--   app.demo_today     "today"; no transaction after it is read        (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive        (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive          (default CUST00100)
--   app.cushion_eur    money kept untouched on the account              (default 100)
-- One row per customer. Every component the coach may quote is a column. Euros, 2 decimals.
-- Safe to save (section 3.1) is part of this row; the bills behind bills_due_eur, one row per bill, are
-- the per-bill output 03_safe_to_spend_bills.sql (section 3.2), which shares this file up to bill_items.

SET statement_timeout = '60s';

WITH
-- ---- shared classification block: begin ------------------------------------------------------
params AS (
    SELECT today,
           (date_trunc('month', today + 1) - interval '6 months')::date AS win_start,
           (date_trunc('month', today + 1) - interval '1 day')::date    AS win_end
    FROM (SELECT COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date AS today) p
),
tx AS (
    SELECT t.id, t.customer_id, t.account_id, t.tx_date, t.tx_at, t.category, t.tx_type,
           t.merchant_id, t.mcc, t.amount_eur, t.balance_after
    FROM transactions t
    WHERE t.customer_id >= COALESCE(NULLIF(current_setting('app.customer_from', true), ''), 'CUST00000')
      AND t.customer_id <  COALESCE(NULLIF(current_setting('app.customer_to', true), ''), 'CUST00100')
      AND t.tx_date <= COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date
),
spike_base AS (   -- the customer's median purchase per category over the 365 days up to today
    SELECT tx.customer_id, tx.category, count(*) AS n_12m,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY -tx.amount_eur) AS median_12m
    FROM tx, params p
    WHERE tx.tx_type = 'purchase' AND tx.tx_date > p.today - 365
    GROUP BY 1, 2
),
merchant_recurring AS (   -- card merchants charged once a month at a stable amount (subscriptions)
    SELECT tx.customer_id, tx.merchant_id
    FROM tx, params p
    WHERE tx.merchant_id IS NOT NULL AND tx.tx_date BETWEEN p.win_start AND p.win_end
    GROUP BY 1, 2
    HAVING count(DISTINCT date_trunc('month', tx.tx_date)) >= 4
       AND count(*) = count(DISTINCT date_trunc('month', tx.tx_date))
       AND stddev_samp(tx.amount_eur) / NULLIF(abs(avg(tx.amount_eur)), 0) <= 0.10
),
overrides (customer_id, merchant_id, mcc, category, basket) AS (
    -- User overrides, most specific match wins (merchant > mcc > category). Empty here; in the
    -- product this is the basket_overrides table described in metrics.md.
    SELECT NULL::text, NULL::text, NULL::text, NULL::text, NULL::text WHERE false
),
cls AS (
    SELECT x.*,
           COALESCE(o.basket,
               CASE
                   WHEN x.flow <> 'spend'                                    THEN NULL
                   WHEN x.tx_type IN ('housing_payment', 'utilities_payment') THEN 'regular_essentials'
                   WHEN x.is_subscription                                     THEN 'regular_essentials'
                   WHEN x.category IN ('Health', 'Home & Tech')               THEN 'unexpected_necessities'
                   WHEN x.category = 'Transportation' AND x.mcc = '4121'      THEN 'everyday_spending'   -- taxi
                   WHEN x.category IN ('Groceries', 'Transportation') AND x.is_one_off
                                                                              THEN 'unexpected_necessities'
                   WHEN x.category IN ('Groceries', 'Transportation')         THEN 'regular_essentials'
                   WHEN x.category IN ('Restaurants', 'Entertainment', 'Lifestyle', 'Travel')
                                                                              THEN 'everyday_spending'
                   ELSE 'unclassified'
               END) AS basket,
           (o.basket IS NOT NULL) AS overridden
    FROM (
        SELECT tx.*,
               CASE WHEN tx.category IN ('Salary', 'Other Income', 'Invest Withdraw') THEN 'income'
                    WHEN tx.category = 'Invest Deposit' THEN 'saving'
                    WHEN tx.category = 'Salary Sweep'   THEN 'transfer'
                    ELSE 'spend' END                                    AS flow,
               -tx.amount_eur                                           AS out_eur,
               COALESCE(tx.tx_type = 'purchase' AND sb.n_12m >= 8
                        AND -tx.amount_eur > 5 * sb.median_12m, false)  AS is_one_off,
               (mr.merchant_id IS NOT NULL)                             AS is_subscription
        FROM tx
        LEFT JOIN spike_base sb ON sb.customer_id = tx.customer_id AND sb.category = tx.category
        LEFT JOIN merchant_recurring mr ON mr.customer_id = tx.customer_id AND mr.merchant_id = tx.merchant_id
    ) x
    LEFT JOIN LATERAL (
        SELECT o.basket FROM overrides o
        WHERE o.customer_id = x.customer_id
          AND (o.merchant_id = x.merchant_id OR o.mcc = x.mcc OR o.category = x.category)
        ORDER BY (o.merchant_id IS NOT NULL) DESC, (o.mcc IS NOT NULL) DESC
        LIMIT 1
    ) o ON true
),
-- ---- shared classification block: end --------------------------------------------------------
-- Recurring series, same rules as 01_recurring.sql.
series_month AS (
    SELECT c.customer_id,
           CASE WHEN c.tx_type = 'purchase' THEN 'merchant' ELSE 'tx_type' END AS series_kind,
           CASE WHEN c.tx_type = 'purchase' THEN c.merchant_id ELSE c.tx_type END AS series_key,
           date_trunc('month', c.tx_date)::date AS month,
           count(*) AS n_tx, sum(abs(c.amount_eur)) AS total_eur,
           min(extract(day FROM c.tx_date))::int AS first_day,
           sign(sum(c.amount_eur))::int AS dir
    FROM cls c, params p
    WHERE c.tx_date BETWEEN p.win_start AND p.win_end
      AND (c.tx_type <> 'purchase' OR c.is_subscription)
    GROUP BY 1, 2, 3, 4
),
recurring AS (
    SELECT customer_id, series_kind, series_key,
           percentile_disc(0.5) WITHIN GROUP (ORDER BY n_tx)      AS tx_per_month,
           (percentile_cont(0.5) WITHIN GROUP (ORDER BY total_eur))::numeric AS typical_month_eur,
           percentile_disc(0.5) WITHIN GROUP (ORDER BY first_day) AS typical_day,
           CASE WHEN sum(dir) > 0 THEN 'in' ELSE 'out' END        AS direction
    FROM series_month
    GROUP BY 1, 2, 3
    HAVING count(*) >= 4
),
done_this_month AS (
    SELECT c.customer_id, CASE WHEN c.tx_type = 'purchase' THEN c.merchant_id ELSE c.tx_type END AS series_key
    FROM cls c, params p
    WHERE c.tx_date >= date_trunc('month', p.today)
    GROUP BY 1, 2
),
salary AS (   -- next payday: the salary series' next expected date (01_recurring.sql rule; on the
              -- typical day itself an unpaid salary is still 'upcoming' and expected tomorrow)
    SELECT r.customer_id,
           CASE
               WHEN d.series_key IS NOT NULL THEN ty.typ_next
               WHEN p.today <= ty.typ_this THEN GREATEST(ty.typ_this, p.today + 1)
               ELSE GREATEST(ty.month_end, p.today + 1)
           END AS next_payday,
           CASE WHEN d.series_key IS NOT NULL THEN 'received_this_month'
                WHEN p.today <= ty.typ_this THEN 'upcoming'
                ELSE 'late' END AS salary_status,
           round(r.typical_month_eur::numeric, 2) AS typical_salary_eur
    FROM recurring r
    CROSS JOIN params p
    CROSS JOIN LATERAL (
        SELECT LEAST(date_trunc('month', p.today)::date + (r.typical_day - 1),
                     (date_trunc('month', p.today) + interval '1 month' - interval '1 day')::date)  AS typ_this,
               LEAST((date_trunc('month', p.today) + interval '1 month')::date + (r.typical_day - 1),
                     (date_trunc('month', p.today) + interval '2 months' - interval '1 day')::date) AS typ_next,
               (date_trunc('month', p.today) + interval '1 month' - interval '1 day')::date          AS month_end
    ) ty
    LEFT JOIN done_this_month d ON d.customer_id = r.customer_id AND d.series_key = r.series_key
    WHERE r.series_key = 'salary'
),
customers_in AS (
    SELECT DISTINCT c.customer_id FROM cls c
),
horizon AS (
    SELECT ci.customer_id,
           COALESCE(s.next_payday, p.today + 30)               AS next_payday,
           COALESCE(s.salary_status, 'no_salary_series')       AS salary_status,
           s.typical_salary_eur,
           (COALESCE(s.next_payday, p.today + 30) - p.today)   AS days_to_payday
    FROM customers_in ci
    CROSS JOIN params p
    LEFT JOIN salary s USING (customer_id)
),
-- Bills due after today and up to and including the next payday. A once-a-month bill counts at its
-- typical day in each month of the horizon. This month's bill counts only if it is not paid yet:
-- up to 7 days past its typical day it counts as due tomorrow, later it is taken as skipped.
-- A bill paid several times a month counts pro rata. Salary Sweep is excluded: it moves the
-- incoming salary on, so it never falls before payday.
bill_dates AS (
    SELECT r.customer_id, r.series_key, r.typical_month_eur, h.next_payday, k,
           LEAST(m + (r.typical_day - 1), (m + interval '1 month' - interval '1 day')::date) AS typical_date,
           (k = 0 AND d.series_key IS NOT NULL) AS already_paid
    FROM recurring r
    JOIN horizon h USING (customer_id)
    CROSS JOIN params p
    CROSS JOIN LATERAL generate_series(0, 2) AS k
    CROSS JOIN LATERAL (SELECT (date_trunc('month', p.today) + make_interval(months => k))::date AS m) mm
    LEFT JOIN done_this_month d ON d.customer_id = r.customer_id AND d.series_key = r.series_key
    WHERE r.direction = 'out' AND r.tx_per_month = 1 AND r.series_key <> 'salary_sweep'
),
bill_due AS (
    SELECT b.*,
           CASE WHEN b.typical_date > p.today      THEN b.typical_date
                WHEN p.today - b.typical_date <= 7 THEN p.today + 1      -- a few days late: due now
                ELSE NULL END AS due_date                               -- long overdue: skipped
    FROM bill_dates b CROSS JOIN params p
    WHERE NOT b.already_paid
),
-- One row per bill that falls due before payday, with its unrounded term of bills_due: a
-- once-a-month bill its typical amount for each due date up to and including payday, a bill paid
-- several times a month its typical month * N / 30.4375. 03_safe_to_spend_bills.sql returns these
-- rows (the per-bill output); its text up to here is identical to this file.
bill_items AS (
    SELECT b.customer_id, b.series_key,
           count(*)                  AS occurrences,
           min(b.due_date)           AS first_due_date,
           0                         AS pro_rata_days,
           sum(b.typical_month_eur)  AS bill_due_eur
    FROM bill_due b
    WHERE b.due_date <= b.next_payday
    GROUP BY b.customer_id, b.series_key
    UNION ALL
    SELECT r.customer_id, r.series_key, 0, NULL, h.days_to_payday,
           r.typical_month_eur * h.days_to_payday / 30.4375
    FROM recurring r
    JOIN horizon h USING (customer_id)
    WHERE r.direction = 'out' AND r.tx_per_month > 1 AND r.series_key <> 'salary_sweep'
),
-- ---- end of the part shared with 03_safe_to_spend_bills.sql ----------------------------------
bills AS (   -- the customer-level total: the sum of the unrounded bill terms, rounded once below
    SELECT h.customer_id, COALESCE(sum(i.bill_due_eur), 0) AS bills_due_eur
    FROM horizon h
    LEFT JOIN bill_items i USING (customer_id)
    GROUP BY h.customer_id
),
budget AS (   -- typical month from the recurring series: income (salary and other income; an investment
              -- withdrawal is the customer's own saving, not income), net of sweeps, minus committed
              -- outflows. A recurring investment deposit counts as committed: it is the customer's own
              -- saving plan, and safe to spend protects it.
    SELECT h.customer_id,
           COALESCE(sum(r.typical_month_eur) FILTER (WHERE r.series_key IN ('salary', 'other_income')), 0) AS income_month_eur,
           COALESCE(sum(r.typical_month_eur) FILTER (WHERE r.series_key = 'salary_sweep'), 0) AS sweep_month_eur,
           COALESCE(sum(r.typical_month_eur) FILTER (WHERE r.direction = 'out'
                                                       AND r.series_key <> 'salary_sweep'), 0) AS committed_month_eur
    FROM horizon h
    LEFT JOIN recurring r USING (customer_id)
    GROUP BY h.customer_id
),
run_rates AS (   -- daily averages over the 6 complete months (or the customer's history if shorter)
    SELECT c.customer_id,
           (p.win_end - GREATEST(p.win_start, min(c.tx_date)) + 1)                                   AS window_days,
           sum(c.out_eur) FILTER (WHERE c.basket = 'regular_essentials' AND c.tx_type = 'purchase'
                                    AND NOT c.is_subscription AND c.tx_date >= p.win_start)        AS essentials_eur,
           sum(c.out_eur) FILTER (WHERE c.basket = 'unexpected_necessities' AND c.tx_date >= p.win_start) AS irregular_eur,
           sum(c.out_eur) FILTER (WHERE c.basket = 'everyday_spending' AND NOT c.is_one_off
                                    AND c.tx_date >= p.win_start)                                   AS everyday_eur
    FROM cls c, params p
    WHERE c.tx_date <= p.win_end
    GROUP BY c.customer_id, p.win_start, p.win_end
),
-- Safe to save (metrics.md 3.1): the everyday_spending category with the largest window total,
-- one-offs left out, on the same basis as the everyday run rate. A sensitive category is never
-- named (R9): Health is skipped, so the next category would be named.
everyday_top AS (
    SELECT DISTINCT ON (c.customer_id) c.customer_id, c.category, sum(c.out_eur) AS category_eur
    FROM cls c, params p
    WHERE c.basket = 'everyday_spending' AND NOT c.is_one_off AND c.category <> 'Health'
      AND c.tx_date BETWEEN p.win_start AND p.win_end
    GROUP BY c.customer_id, c.category
    ORDER BY c.customer_id, sum(c.out_eur) DESC, c.category
),
balance AS (   -- sum over the customer's accounts of the last balance_after on or before today
    SELECT customer_id, sum(balance_after) AS balance_eur, max(id) AS balance_tx_id, max(tx_at) AS balance_at
    FROM (SELECT DISTINCT ON (account_id) customer_id, account_id, balance_after, id, tx_at
          FROM tx ORDER BY account_id, tx_at DESC, id DESC) last_per_account
    GROUP BY customer_id
),
calc AS (
    SELECT h.customer_id, p.today, h.next_payday, h.salary_status, h.typical_salary_eur, h.days_to_payday,
           b.balance_eur, b.balance_tx_id, bl.bills_due_eur,
           bu.income_month_eur, bu.sweep_month_eur, bu.committed_month_eur,
           -- No history inside the window (a customer whose first transaction is in the current month):
           -- the run-rates are 0 and window_days is 0, and the row is still returned.
           COALESCE(rr.essentials_eur / NULLIF(rr.window_days, 0), 0) AS essentials_per_day,
           COALESCE(rr.irregular_eur  / NULLIF(rr.window_days, 0), 0) AS irregular_per_day,
           COALESCE(rr.everyday_eur   / NULLIF(rr.window_days, 0), 0) AS everyday_per_day,
           COALESCE(rr.window_days, 0)                                AS window_days,
           et.category                                                AS top_everyday_category,
           COALESCE(et.category_eur / NULLIF(rr.window_days, 0), 0)   AS top_everyday_per_day,
           COALESCE(NULLIF(current_setting('app.cushion_eur', true), ''), '100')::numeric AS cushion_eur
    FROM horizon h
    CROSS JOIN params p
    JOIN balance b USING (customer_id)
    JOIN bills bl USING (customer_id)
    JOIN budget bu USING (customer_id)
    LEFT JOIN run_rates rr USING (customer_id)
    LEFT JOIN everyday_top et USING (customer_id)
),
limits AS (
    SELECT c.*,
           c.essentials_per_day * c.days_to_payday AS essentials_reserve_eur,
           c.irregular_per_day  * c.days_to_payday AS irregular_reserve_eur,
           -- A. balance limit: what the account can carry until payday without dropping below the cushion
           c.balance_eur - c.bills_due_eur - (c.essentials_per_day + c.irregular_per_day) * c.days_to_payday
               - c.cushion_eur AS free_until_payday_eur,
           -- B. budget limit: the typical month's money left after commitments, essentials and the irregular reserve
           c.income_month_eur - c.sweep_month_eur - c.committed_month_eur
               - (c.essentials_per_day + c.irregular_per_day) * 30.4375 AS free_month_eur
    FROM calc c
),
result AS (
    SELECT l.*,
           GREATEST(l.free_until_payday_eur, 0) / l.days_to_payday * LEAST(7, l.days_to_payday) AS balance_limit_7d,
           GREATEST(l.free_month_eur, 0) * 7 / 30.4375                                       AS budget_limit_7d,
           -- safe to save (metrics.md 3.1), from the same unrounded terms
           l.everyday_per_day * l.days_to_payday                                             AS everyday_until_payday,
           l.everyday_per_day * 30.4375                                                      AS everyday_month,
           round(GREATEST(l.free_month_eur - l.everyday_per_day * 30.4375, 0), 2)            AS safe_to_save_monthly
    FROM limits l
)
SELECT customer_id,
       round(LEAST(balance_limit_7d, budget_limit_7d), 2) AS safe_to_spend_7d_eur,
       CASE WHEN balance_limit_7d <= budget_limit_7d THEN 'balance' ELSE 'budget' END AS binding_limit,
       round(balance_limit_7d, 2)         AS balance_limit_7d_eur,
       round(budget_limit_7d, 2)          AS budget_limit_7d_eur,
       round(free_until_payday_eur, 2)    AS free_until_payday_eur,
       round(free_month_eur, 2)           AS free_month_eur,
       round(balance_eur, 2)              AS balance_eur,
       balance_tx_id,
       round(bills_due_eur, 2)            AS bills_due_eur,
       round(essentials_reserve_eur, 2)   AS essentials_reserve_eur,
       round(irregular_reserve_eur, 2)    AS irregular_reserve_eur,
       cushion_eur,
       next_payday,
       days_to_payday,
       salary_status,
       round(income_month_eur, 2)         AS income_month_eur,
       round(sweep_month_eur, 2)          AS sweep_month_eur,
       round(committed_month_eur, 2)      AS committed_month_eur,
       round(essentials_per_day * 30.4375, 2) AS essentials_month_eur,
       round(irregular_per_day * 30.4375, 2)  AS irregular_month_eur,
       window_days,
       round(everyday_per_day * 7, 2)      AS usual_everyday_7d_eur,
       CASE WHEN LEAST(balance_limit_7d, budget_limit_7d) <= 0 THEN 'nothing_free'
            WHEN LEAST(balance_limit_7d, budget_limit_7d) < everyday_per_day * 7 THEN 'below_usual'
            ELSE 'ok' END                 AS status,
       today + 1                          AS week_start,
       today + 7                          AS week_end,
       -- safe to save (metrics.md 3.1). A stock: money on the account now beyond what is needed until
       -- payday, everyday spending included. Never below 0.
       round(everyday_until_payday, 2)    AS everyday_until_payday_eur,
       round(GREATEST(free_until_payday_eur - everyday_until_payday, 0), 2) AS safe_to_save_eur,
       -- A flow: what a typical month leaves after commitments, both reserves and everyday spending.
       round(everyday_month, 2)           AS everyday_month_eur,
       safe_to_save_monthly               AS safe_to_save_monthly_eur,
       round(GREATEST(-free_month_eur, 0), 2) AS essentials_shortfall_month_eur,
       -- Why the month leaves nothing: only when safe_to_save_monthly_eur is 0, by the sign of free month.
       CASE WHEN safe_to_save_monthly > 0 THEN NULL
            WHEN free_month_eur < 0       THEN 'essentials_exceed_income'
            ELSE 'largest_everyday_category' END AS save_reason,
       CASE WHEN safe_to_save_monthly = 0 AND free_month_eur >= 0
            THEN top_everyday_category END    AS save_reason_category,
       CASE WHEN safe_to_save_monthly > 0 THEN NULL
            WHEN free_month_eur < 0       THEN round(-free_month_eur, 2)
            ELSE round(top_everyday_per_day * 30.4375, 2) END AS save_reason_month_eur
FROM result
ORDER BY customer_id;
