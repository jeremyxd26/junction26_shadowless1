-- Metric 5: spender profile ("What kind of spender am I?").  Definition: docs/design/metrics.md, section 5.
--
-- Inputs (session settings, all optional):
--   app.demo_today     "today"; no transaction after it is read        (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive        (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive          (default CUST00100)
--   app.tx_labels      the customer's transaction labels, JSON {"<id>": "<basket>"} (default none)
-- One row per customer: the features over the last 6 complete months, then one primary label
-- chosen by the first matching rule, and any number of the five trait tags. No feature uses the
-- Health category or health MCCs on its own (rule R9): they only count inside the basket totals.
-- "Income" is Salary + Other Income; Invest Withdraw is the customer's own saving coming back and
-- is not income. A "sweep customer" has a Salary Sweep in at least 4 of the 6 window months.

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
months AS (   -- months covered by the customer's history inside the window (1..6), as in 02_baskets.sql
    SELECT c.customer_id,
           GREATEST(1, LEAST(6, (extract(year FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int * 12
                                + extract(month FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int))) AS n_months
    FROM cls c, params p
    GROUP BY c.customer_id, p.win_end
),
w AS (   -- the window's transactions
    SELECT c.* FROM cls c, params p WHERE c.tx_date BETWEEN p.win_start AND p.win_end
),
monthly AS (   -- per calendar month: did spending plus saving exceed net income (income minus sweep)?
    SELECT customer_id, date_trunc('month', tx_date) AS month,
           sum(amount_eur) FILTER (WHERE category IN ('Salary', 'Other Income') OR flow = 'transfer') AS net_in,
           sum(out_eur)    FILTER (WHERE flow IN ('spend', 'saving'))     AS out_total
    FROM w GROUP BY 1, 2
),
top_everyday AS (
    SELECT DISTINCT ON (customer_id) customer_id, category AS top_everyday_category, sum(out_eur) AS top_eur
    FROM w WHERE basket = 'everyday_spending'
    GROUP BY customer_id, category
    ORDER BY customer_id, sum(out_eur) DESC, category
),
f AS (
    SELECT w.customer_id, m.n_months,
           COALESCE(sum(w.amount_eur) FILTER (WHERE w.category IN ('Salary', 'Other Income')), 0) / m.n_months AS income_month,
           COALESCE(sum(w.out_eur) FILTER (WHERE w.flow = 'transfer'), 0) / m.n_months         AS sweep_month,
           count(DISTINCT date_trunc('month', w.tx_date)) FILTER (WHERE w.flow = 'transfer')   AS sweep_months,
           COALESCE(sum(w.out_eur) FILTER (WHERE w.flow = 'spend'), 0) / m.n_months            AS spend_month,
           COALESCE(sum(w.out_eur) FILTER (WHERE w.flow = 'saving'), 0) / m.n_months           AS saving_month,
           COALESCE(sum(w.out_eur) FILTER (WHERE w.basket = 'regular_essentials'), 0)          AS regular_eur,
           COALESCE(sum(w.out_eur) FILTER (WHERE w.basket = 'unexpected_necessities'), 0)      AS unexpected_eur,
           COALESCE(sum(w.out_eur) FILTER (WHERE w.basket = 'everyday_spending'), 0)           AS everyday_eur,
           COALESCE(sum(w.out_eur) FILTER (WHERE w.flow = 'spend' AND w.is_one_off
                                             AND w.category <> 'Health'), 0)                   AS one_off_eur,  -- R9
           COALESCE(sum(w.out_eur) FILTER (WHERE w.basket = 'everyday_spending'
                                             AND extract(isodow FROM w.tx_at) >= 6), 0)       AS everyday_weekend_eur,
           count(*) FILTER (WHERE w.basket = 'everyday_spending')                            AS everyday_n,
           count(*) FILTER (WHERE w.balance_after < 0)                                        AS n_tx_below_zero
    FROM w JOIN months m USING (customer_id)
    GROUP BY w.customer_id, m.n_months
),
g AS (
    SELECT f.*,
           f.income_month - f.sweep_month                                         AS net_income_month,
           f.regular_eur + f.unexpected_eur + f.everyday_eur                      AS spend_total,
           (SELECT count(*) FROM monthly mo WHERE mo.customer_id = f.customer_id
              AND mo.out_total > COALESCE(mo.net_in, 0))                          AS months_out_over_in
    FROM f
),
h AS (
    SELECT g.*,
           CASE WHEN g.net_income_month > 0          -- no keep rate without positive net income
                THEN 100 * (g.net_income_month - g.spend_month) / g.net_income_month END AS keep_rate,
           100 * g.everyday_eur / NULLIF(g.spend_total, 0)                            AS everyday_share,
           100 * g.one_off_eur  / NULLIF(g.spend_total, 0)                            AS one_off_share,
           100 * g.everyday_weekend_eur / NULLIF(g.everyday_eur, 0)                   AS weekend_share,
           g.everyday_n::numeric / g.n_months                                         AS everyday_tx_month
    FROM g
)
SELECT h.customer_id,
       -- Primary label: first matching rule. Thresholds are fixed constants (calibrated once on the
       -- sample's percentiles, see metrics.md), so one customer's label never depends on who else is in the run.
       CASE WHEN h.keep_rate IS NULL                                     THEN 'not_enough_income_data'
            WHEN h.keep_rate < 0                                         THEN 'stretched'
            WHEN COALESCE(h.one_off_share, 0) >= 5                       THEN 'big_ticket'
            WHEN COALESCE(h.everyday_share, 0) >= 30                     THEN 'everyday_heavy'
            WHEN h.keep_rate >= 20                                       THEN 'saver'
            ELSE 'steady' END                                            AS profile,
       array_remove(ARRAY[
            CASE WHEN h.sweep_months >= 4 THEN 'salary_moved_elsewhere' END,   -- sweep customer
            CASE WHEN h.n_tx_below_zero > 0 THEN 'went_below_zero' END,
            CASE WHEN h.saving_month > 0 THEN 'regular_investor' END,
            CASE WHEN COALESCE(h.weekend_share, 0) >= 45 THEN 'weekend_spender' END,
            CASE WHEN h.everyday_tx_month >= 12 THEN 'frequent_small_purchases' END
       ], NULL)                                                          AS traits,
       round(h.keep_rate, 1)                                                     AS keep_rate_pct,
       round(h.net_income_month, 2)                                              AS net_income_month_eur,
       round(h.spend_month, 2)                                                   AS spend_month_eur,
       round(h.saving_month, 2)                                                  AS saving_month_eur,
       round(100 * h.regular_eur    / NULLIF(h.spend_total, 0), 1)               AS regular_share_pct,
       round(100 * h.unexpected_eur / NULLIF(h.spend_total, 0), 1)               AS unexpected_share_pct,
       round(h.everyday_share, 1)                                                AS everyday_share_pct,
       round(h.one_off_share, 1)                                                 AS one_off_share_pct,
       round(h.weekend_share, 1)                                                 AS everyday_weekend_pct,
       round(h.everyday_eur / NULLIF(h.everyday_n, 0), 2)                        AS everyday_avg_ticket_eur,
       round(h.everyday_tx_month, 1)                                             AS everyday_tx_month,
       t.top_everyday_category,
       h.months_out_over_in,
       h.n_tx_below_zero,
       h.n_months,
       p.win_start AS period_start,
       p.win_end   AS period_end
FROM h
LEFT JOIN top_everyday t USING (customer_id)
CROSS JOIN params p
ORDER BY h.customer_id;
