-- Metric 3, per-bill output: the bills due before payday, one row per bill.
-- Definition: docs/design/metrics.md, section 3 (bills_due) and 3.2 (this output).
--
-- The text from `SET statement_timeout` up to the line "end of the part shared with
-- 03_safe_to_spend_bills.sql" is identical to 03_safe_to_spend.sql (a test checks it), so every row's
-- bill_due_eur is exactly one unrounded term of 03's bills_due_eur. bills_due_eur is that sum rounded
-- once; the rows are rounded one by one, so their sum may differ from it by up to 0.01 per row.
--
-- Inputs (session settings, all optional): app.demo_today, app.customer_from, app.customer_to, app.tx_labels, as in 03.
-- One row per bill that falls due after today and up to and including the next payday. Euros, 2 decimals.

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
overrides (customer_id, tx_id, merchant_id, mcc, category, basket) AS MATERIALIZED (
    -- User overrides, most specific match wins (transaction > merchant > mcc > category).
    -- Transaction level: the customer's labels from spike reviews (metrics.md section 1.1), passed as
    -- JSON {"<transaction id>": "<basket>"} in app.tx_labels by core/tools/metric_sql.py. A missing,
    -- empty or malformed setting means no labels; keys that are not ids and values that are not one
    -- of the four basket states are ignored. They apply to the spend flow only, as in classify.py.
    -- Rule level (merchant, mcc, category): empty here; in the product this is the basket_overrides
    -- table described in metrics.md.
    SELECT NULL::text, CASE WHEN l.key ~ '^[0-9]{1,18}$' THEN l.key::bigint END,
           NULL::text, NULL::text, NULL::text, l.value
    FROM (SELECT COALESCE(current_setting('app.tx_labels', true), '') AS s) setting,
         jsonb_each_text(CASE WHEN NOT pg_input_is_valid(setting.s, 'jsonb')    THEN '{}'::jsonb
                              WHEN jsonb_typeof(setting.s::jsonb) <> 'object' THEN '{}'::jsonb
                              ELSE setting.s::jsonb END) AS l
    WHERE l.key ~ '^[0-9]{1,18}$'
      AND l.value IN ('unclassified', 'regular_essentials', 'unexpected_necessities', 'everyday_spending')
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
               CASE WHEN tx.category IN ('Salary', 'Other Income') THEN 'income'
                    WHEN tx.category = 'Invest Withdraw' THEN 'own_savings_back'  -- not income (metrics.md 2.3)
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
        WHERE (o.tx_id = x.id AND x.flow = 'spend')
           OR (o.customer_id = x.customer_id
               AND (o.merchant_id = x.merchant_id OR o.mcc = x.mcc OR o.category = x.category))
        ORDER BY (o.tx_id IS NOT NULL) DESC, (o.merchant_id IS NOT NULL) DESC, (o.mcc IS NOT NULL) DESC
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
series_status AS (   -- this month's status of a once-a-month bill, the 01_recurring.sql rule for a bill
    SELECT b.customer_id, b.series_key,
           CASE WHEN b.already_paid                  THEN 'done_this_month'
                WHEN b.typical_date >= p.today       THEN 'upcoming'
                WHEN p.today - b.typical_date <= 7   THEN 'late'
                ELSE 'skipped_this_month' END AS status
    FROM bill_dates b CROSS JOIN params p
    WHERE b.k = 0
),
series_category AS (   -- the dataset category of the series' transactions in the window
    SELECT c.customer_id,
           CASE WHEN c.tx_type = 'purchase' THEN 'merchant' ELSE 'tx_type' END   AS series_kind,
           CASE WHEN c.tx_type = 'purchase' THEN c.merchant_id ELSE c.tx_type END AS series_key,
           mode() WITHIN GROUP (ORDER BY c.category)                             AS category
    FROM cls c, params p
    WHERE c.tx_date BETWEEN p.win_start AND p.win_end
      AND (c.tx_type <> 'purchase' OR c.is_subscription)
    GROUP BY 1, 2, 3
)
SELECT i.customer_id,
       r.series_kind,
       i.series_key,
       sc.category,
       -- English label for reading the output; the app shows the tool's labels (aliases for merchants)
       CASE WHEN r.series_kind = 'merchant'          THEN sc.category || ' subscription'
            WHEN i.series_key = 'housing_payment'    THEN 'Housing'
            WHEN i.series_key = 'utilities_payment'  THEN 'Utilities'
            WHEN i.series_key = 'investment_deposit' THEN 'Investment deposit'
            ELSE initcap(replace(i.series_key, '_', ' ')) END AS label,
       CASE WHEN r.tx_per_month > 1 THEN 'spread' ELSE st.status END AS status,
       round(r.typical_month_eur, 2) AS typical_month_eur,
       i.occurrences,                 -- once-a-month bill: due dates up to and including payday
       i.first_due_date,
       i.pro_rata_days,               -- spread bill: N, the days to payday; typical month * N / 30.4375
       round(i.bill_due_eur, 2)      AS bill_due_eur,
       h.next_payday,
       h.days_to_payday
FROM bill_items i
JOIN recurring r ON r.customer_id = i.customer_id AND r.series_key = i.series_key
JOIN horizon h ON h.customer_id = i.customer_id
LEFT JOIN series_status st ON st.customer_id = i.customer_id AND st.series_key = i.series_key
LEFT JOIN series_category sc ON sc.customer_id = i.customer_id AND sc.series_kind = r.series_kind
                            AND sc.series_key = i.series_key
ORDER BY i.customer_id, i.bill_due_eur DESC, i.series_key;
