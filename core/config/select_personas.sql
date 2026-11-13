-- Demo persona screening: one row per customer in a customer_id range with the checks of issue #22.
-- Method and results: docs/design/personas.md. Driver: core/config/select_personas.py, which runs
-- this file and core/metrics/01, 03 and 05 for one candidate at a time.
--
-- Inputs (session settings, all optional, same convention as core/metrics/*.sql):
--   app.demo_today     "today"; no transaction after it is read        (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive        (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive          (default CUST00100)
-- Keep ranges at 100 customers or fewer. Every read of transactions carries the customer range and
-- the DEMO_TODAY bound directly in WHERE, so the planner uses the (customer_id, ...) indexes.
--
-- Periods for today = 2026-09-30:
--   last month      2026-08-01 .. 2026-08-31   (taxi rides)
--   window          2026-04-01 .. 2026-09-30   (last 6 complete months, metrics.md section 0; the
--                                               what-if baseline). Salary, housing, sweep, dining.
--   prev6           2026-03-01 .. 2026-08-31   (the 6 months before the month in progress). Dining.
--   recent          2026-07-01 .. 2026-09-30   (the last three months, unexpected necessities)
-- "Restaurant spending in the last 6 months" is counted in both readings of "last 6 months" and the
-- smaller count is kept (dining_months_of_6), so a persona passes whichever reading the demo uses.

SET statement_timeout = '60s';

WITH params AS (
    SELECT today,
           (date_trunc('month', today + 1) - interval '6 months')::date AS win_start,
           (date_trunc('month', today + 1) - interval '1 day')::date    AS win_end,
           date_trunc('month', today)::date                              AS month_start,
           (date_trunc('month', today) - interval '1 month')::date       AS last_month_start,
           (date_trunc('month', today) - interval '1 day')::date         AS last_month_end,
           (date_trunc('month', today) - interval '6 months')::date      AS dining_start,
           (date_trunc('month', today) - interval '2 months')::date      AS recent_start
    FROM (SELECT COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date AS today) p
),
tx AS (
    SELECT t.id, t.customer_id, t.tx_date, t.category, t.tx_type, t.merchant_id, t.mcc, t.amount_eur
    FROM transactions t
    WHERE t.customer_id >= COALESCE(NULLIF(current_setting('app.customer_from', true), ''), 'CUST00000')
      AND t.customer_id <  COALESCE(NULLIF(current_setting('app.customer_to', true), ''), 'CUST00100')
      AND t.tx_date <= COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date
),
spike_base AS (   -- one-off rule of metrics.md section 0: median purchase per category over 365 days
    SELECT tx.customer_id, tx.category, count(*) AS n_12m,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY -tx.amount_eur) AS median_12m
    FROM tx, params p
    WHERE tx.tx_type = 'purchase' AND tx.tx_date > p.today - 365
    GROUP BY 1, 2
),
-- Unexpected necessities of the last three months, Health left out (R9: a persona story never rests
-- on health spending). Basket rules 3 and 5 of metrics.md: Home & Tech always; Groceries and
-- Transportation (not taxi) only when the purchase is a one-off.
recent_unexpected AS (
    SELECT DISTINCT ON (tx.customer_id)
           tx.customer_id, tx.id AS unexp_tx_id, tx.tx_date AS unexp_date, tx.category AS unexp_category,
           -tx.amount_eur AS unexp_eur,
           COALESCE(sb.n_12m >= 8 AND -tx.amount_eur > 5 * sb.median_12m, false) AS unexp_is_one_off,
           round((-tx.amount_eur / NULLIF(sb.median_12m, 0))::numeric, 1)        AS unexp_x_median
    FROM tx
    CROSS JOIN params p
    LEFT JOIN spike_base sb ON sb.customer_id = tx.customer_id AND sb.category = tx.category
    WHERE tx.tx_type = 'purchase' AND tx.tx_date >= p.recent_start
      AND (tx.category = 'Home & Tech'
           OR (tx.category IN ('Groceries', 'Transportation') AND tx.mcc IS DISTINCT FROM '4121'
               AND sb.n_12m >= 8 AND -tx.amount_eur > 5 * sb.median_12m))
    ORDER BY tx.customer_id, -tx.amount_eur DESC, tx.id DESC
),
checks AS (
    SELECT tx.customer_id,
           count(*) FILTER (WHERE tx.mcc = '4121' AND tx.tx_date BETWEEN p.last_month_start AND p.last_month_end)
                                                                                AS taxi_n_last_month,
           COALESCE(sum(-tx.amount_eur) FILTER (WHERE tx.mcc = '4121'
                    AND tx.tx_date BETWEEN p.last_month_start AND p.last_month_end), 0) AS taxi_eur_last_month,
           count(DISTINCT date_trunc('month', tx.tx_date)) FILTER (WHERE tx.mcc IN ('5812', '5813', '5814')
                    AND tx.tx_date BETWEEN p.win_start AND p.win_end)           AS dining_months_window,
           count(DISTINCT date_trunc('month', tx.tx_date)) FILTER (WHERE tx.mcc IN ('5812', '5813', '5814')
                    AND tx.tx_date >= p.dining_start AND tx.tx_date < p.month_start) AS dining_months_prev6,
           count(DISTINCT date_trunc('month', tx.tx_date)) FILTER (WHERE tx.tx_type = 'salary'
                    AND tx.tx_date BETWEEN p.win_start AND p.win_end)           AS salary_months,
           count(DISTINCT date_trunc('month', tx.tx_date)) FILTER (WHERE tx.tx_type = 'housing_payment'
                    AND tx.tx_date BETWEEN p.win_start AND p.win_end)           AS housing_months,
           count(*) FILTER (WHERE tx.tx_type = 'housing_payment' AND tx.tx_date >= p.month_start)
                                                                                AS housing_this_month,
           count(DISTINCT date_trunc('month', tx.tx_date)) FILTER (WHERE tx.category = 'Salary Sweep'
                    AND tx.tx_date BETWEEN p.win_start AND p.win_end)           AS sweep_months,
           COALESCE(sum(-tx.amount_eur) FILTER (WHERE tx.tx_type = 'housing_payment'
                    AND tx.tx_date BETWEEN p.win_start AND p.win_end), 0)       AS housing_window_eur
    FROM tx, params p
    GROUP BY tx.customer_id
)
SELECT cu.customer_id,
       cu.age,
       cu.postal_code,
       CASE WHEN cu.age < 25 THEN '18-24' WHEN cu.age < 35 THEN '25-34' WHEN cu.age < 45 THEN '35-44'
            WHEN cu.age < 55 THEN '45-54' WHEN cu.age < 65 THEN '55-64' WHEN cu.age < 75 THEN '65-74'
            ELSE '75+' END                         AS age_band,      -- bands of metrics.md section 6
       left(cu.postal_code, 3)                     AS area3,
       left(cu.postal_code, 2)                     AS city2,
       c.taxi_n_last_month,
       round(c.taxi_eur_last_month, 2)             AS taxi_eur_last_month,
       c.dining_months_window,
       c.dining_months_prev6,
       LEAST(c.dining_months_window, c.dining_months_prev6) AS dining_months_of_6,   -- 6 = every month in both readings
       c.salary_months,
       c.housing_months,
       c.housing_this_month,
       round(c.housing_window_eur, 2)              AS housing_window_eur,
       c.sweep_months,
       ru.unexp_tx_id,
       ru.unexp_date,
       ru.unexp_category,
       round(ru.unexp_eur, 2)                      AS unexp_eur,
       ru.unexp_is_one_off,
       ru.unexp_x_median,
       p.today                                     AS as_of
FROM customers cu
JOIN checks c USING (customer_id)
CROSS JOIN params p
LEFT JOIN recent_unexpected ru USING (customer_id)
WHERE cu.customer_id >= COALESCE(NULLIF(current_setting('app.customer_from', true), ''), 'CUST00000')
  AND cu.customer_id <  COALESCE(NULLIF(current_setting('app.customer_to', true), ''), 'CUST00100')
ORDER BY cu.customer_id;
