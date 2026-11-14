-- Metric 12: small everyday purchases, the ones nobody notices one by one (#256).
-- Definition: docs/design/metrics.md, section 12. The tool core/tools/small_purchases.py computes the
-- same numbers in Python (core/tools/classify.py is this block's twin); this file is their reference.
--
-- Inputs (session settings, all optional):
--   app.demo_today     "today"; no transaction after it is read        (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive        (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive          (default CUST00100)
--   app.tx_labels      the customer's transaction labels, JSON {"<id>": "<basket>"} (default none)
--   app.small_start    first day of the period        (default: the start of the last 3 complete months)
--   app.small_end      last day of the period         (default: their last day; periods.py last_3_months)
--   app.small_max      the largest amount that counts as small, euros   (default 10.00)
-- A small purchase is money out (amount_eur < 0) of the spend flow in the basket everyday_spending, in
-- Restaurants, Entertainment or Lifestyle, of at most app.small_max euros. A refund is never a purchase;
-- it still lowers everyday spending, as in the baskets.
-- Result: per customer one row with category = 'all' (count, total_eur, avg_eur, month_avg_eur when the
-- period is whole months, share_pct of everyday spending, flexible_total_eur), then one row per category
-- with small purchases (count, total_eur,
-- share_pct of the small total), largest first. Money is positive euros, rounded as the tool rounds:
-- the average and the shares are computed from the totals rounded to cents.
-- The CTEs from "params" to "cls" are the shared classification block of 02-06; keep the copies identical.

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
small_params AS (   -- the default period: the last 3 complete months (core/tools/periods.py last_3_months)
    SELECT COALESCE(NULLIF(current_setting('app.small_start', true), ''),
                    to_char(date_trunc('month', p.today + 1) - interval '3 months', 'YYYY-MM-DD'))::date AS start_date,
           COALESCE(NULLIF(current_setting('app.small_end', true), ''),
                    to_char(date_trunc('month', p.today + 1) - interval '1 day', 'YYYY-MM-DD'))::date    AS end_date,
           COALESCE(NULLIF(current_setting('app.small_max', true), ''), '10.00')::numeric               AS max_eur
    FROM params p
),
small_months AS (   -- whole calendar months in the period, or NULL when it is not made of whole months
    SELECT CASE WHEN q.start_date = date_trunc('month', q.start_date)::date
                 AND q.end_date = (date_trunc('month', q.end_date) + interval '1 month' - interval '1 day')::date
                THEN (12 * (extract(year FROM q.end_date) - extract(year FROM q.start_date))
                      + extract(month FROM q.end_date) - extract(month FROM q.start_date) + 1)::int END AS months
    FROM small_params q
),
customers AS (
    SELECT DISTINCT customer_id FROM tx
),
everyday AS (   -- everyday spending in the period, refunds netted (as the baskets count it)
    SELECT c.customer_id, sum(c.out_eur) AS flexible_eur
    FROM cls c, small_params q
    WHERE c.flow = 'spend' AND c.basket = 'everyday_spending' AND c.tx_date BETWEEN q.start_date AND q.end_date
    GROUP BY 1
),
small AS (   -- the small purchases
    SELECT c.customer_id, c.category, c.out_eur
    FROM cls c, small_params q
    WHERE c.flow = 'spend' AND c.basket = 'everyday_spending'
      AND c.category IN ('Restaurants', 'Entertainment', 'Lifestyle')
      AND c.amount_eur < 0 AND c.out_eur <= q.max_eur
      AND c.tx_date BETWEEN q.start_date AND q.end_date
),
totals AS (
    SELECT cu.customer_id, 'all'::text AS category, count(s.out_eur) AS n,
           round(COALESCE(sum(s.out_eur), 0), 2) AS total
    FROM customers cu
    LEFT JOIN small s ON s.customer_id = cu.customer_id
    GROUP BY 1
),
by_category AS (
    SELECT customer_id, category, count(*) AS n, round(sum(out_eur), 2) AS total
    FROM small
    GROUP BY 1, 2
)
SELECT r.customer_id,
       r.category,
       r.n                                                                            AS count,
       r.total                                                                        AS total_eur,
       CASE WHEN r.category = 'all' AND r.n > 0 THEN round(r.total / r.n, 2) END       AS avg_eur,
       CASE WHEN r.category = 'all' AND m.months > 0 THEN round(r.total / m.months, 2) END AS month_avg_eur,
       CASE WHEN r.category = 'all' THEN round(COALESCE(e.flexible_eur, 0), 2) END     AS flexible_total_eur,
       CASE WHEN r.category = 'all' AND round(COALESCE(e.flexible_eur, 0), 2) > 0
                THEN round(100 * r.total / round(e.flexible_eur, 2), 1)
            WHEN r.category <> 'all' AND t.total > 0
                THEN round(100 * r.total / t.total, 1) END                             AS share_pct,
       q.max_eur                                                                      AS max_amount_eur,
       q.start_date                                                                   AS period_start,
       q.end_date                                                                     AS period_end
FROM (SELECT * FROM totals UNION ALL SELECT * FROM by_category) r
JOIN totals t ON t.customer_id = r.customer_id
LEFT JOIN everyday e ON e.customer_id = r.customer_id
CROSS JOIN small_params q
CROSS JOIN small_months m
ORDER BY r.customer_id, (r.category <> 'all'), r.total DESC, r.category;
