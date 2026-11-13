-- Metric 1: three spending baskets (regular essentials / unexpected necessities / everyday spending).
-- Definition: docs/design/metrics.md, section 1.
--
-- Inputs (session settings, all optional):
--   app.demo_today     "today"; no transaction after it is read        (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive        (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive          (default CUST00100)
-- Result: one row per customer and basket over the last 6 complete calendar months,
-- with monthly averages and the one-off part shown separately. Spend is positive euros.
-- The CTEs from "params" to "cls" are the shared classification block; files 03-06 carry the
-- same block. Keep the copies identical.

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
months AS (   -- months actually covered by the customer's history inside the window (1..6)
    SELECT c.customer_id,
           GREATEST(1, LEAST(6, (extract(year FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int * 12
                                + extract(month FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int))) AS n_months
    FROM cls c, params p
    GROUP BY c.customer_id, p.win_end
),
spend AS (
    SELECT c.customer_id, c.basket,
           sum(c.out_eur)                                    AS total_eur,
           sum(c.out_eur) FILTER (WHERE c.is_one_off)        AS one_off_eur,
           count(*)                                          AS n_tx,
           count(*) FILTER (WHERE c.is_one_off)              AS n_one_off
    FROM cls c, params p
    WHERE c.flow = 'spend' AND c.tx_date BETWEEN p.win_start AND p.win_end
    GROUP BY 1, 2
)
SELECT s.customer_id,
       s.basket,
       round(s.total_eur / m.n_months, 2)                                   AS month_avg_eur,
       round((s.total_eur - COALESCE(s.one_off_eur, 0)) / m.n_months, 2)    AS month_avg_excl_one_off_eur,
       round(COALESCE(s.one_off_eur, 0), 2)                                 AS one_off_total_eur,
       s.n_one_off,
       round(100 * s.total_eur / sum(s.total_eur) OVER (PARTITION BY s.customer_id), 1) AS share_pct,
       round(s.total_eur, 2)                                                AS total_eur,
       s.n_tx,
       m.n_months,
       p.win_start AS period_start,
       p.win_end   AS period_end
FROM spend s
JOIN months m USING (customer_id)
CROSS JOIN params p
ORDER BY s.customer_id,
         array_position(ARRAY['regular_essentials', 'unexpected_necessities', 'everyday_spending', 'unclassified'], s.basket);
