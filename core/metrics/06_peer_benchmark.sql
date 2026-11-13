-- Metric 6: peer benchmark by age band and postal area.  Definition: docs/design/metrics.md, section 6.
--
-- Inputs (session settings, all optional):
--   app.demo_today     "today"; no transaction after it is read        (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive        (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive          (default CUST00100)
--   app.peer_min_n     smallest peer group that may be shown            (default 20)
-- Peers: when the marts built by core/marts/build.py hold rows for as_of = today, the peers are the
-- whole population from metric_peer_flags and metric_customer_month. Otherwise (no build for this
-- today) the peers fall back to the customers inside the range. The customer's own values are always
-- computed live from transactions. The mart tables must exist (core/marts/schema.sql); they may be empty.
-- One row per customer and benchmarked metric (monthly euros over the last 6 complete months).
-- Health is not benchmarked (rule R9). Customers with a monthly Salary Sweep spend mostly from
-- another account: they never enter a peer group and their own rows say comparable = false.
-- percentile = share of the other peers in the group who spend less per month.

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
months AS (   -- months covered by the customer's history inside the window (1..6), as in 02_baskets.sql
    SELECT c.customer_id,
           GREATEST(1, LEAST(6, (extract(year FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int * 12
                                + extract(month FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int))) AS n_months
    FROM cls c, params p
    GROUP BY c.customer_id, p.win_end
),
metric_list (metric, ord) AS (
    VALUES ('spend_total', 1), ('regular_essentials', 2), ('unexpected_necessities', 3), ('everyday_spending', 4),
           ('Groceries', 5), ('Restaurants', 6), ('Transportation', 7), ('Entertainment', 8), ('Lifestyle', 9),
           ('Travel', 10), ('Home & Tech', 11), ('Utilities', 12), ('Housing', 13)
),
sums AS (
    SELECT c.customer_id, u.metric, sum(c.out_eur) AS eur
    FROM cls c
    CROSS JOIN params p
    CROSS JOIN LATERAL (VALUES ('spend_total'), (c.basket), (c.category)) AS u (metric)
    WHERE c.flow = 'spend' AND c.tx_date BETWEEN p.win_start AND p.win_end
    GROUP BY 1, 2
),
cust AS (
    SELECT cu.customer_id, cu.age, cu.postal_code,
           CASE WHEN cu.age < 25 THEN '18-24' WHEN cu.age < 35 THEN '25-34' WHEN cu.age < 45 THEN '35-44'
                WHEN cu.age < 55 THEN '45-54' WHEN cu.age < 65 THEN '55-64' WHEN cu.age < 75 THEN '65-74'
                ELSE '75+' END                       AS age_band,
           left(cu.postal_code, 3)                   AS area3,     -- e.g. 005xx
           left(cu.postal_code, 2)                   AS city2      -- 00 Helsinki, 01 Vantaa, 02 Espoo and Kauniainen
    FROM customers cu
    WHERE cu.customer_id >= COALESCE(NULLIF(current_setting('app.customer_from', true), ''), 'CUST00000')
      AND cu.customer_id <  COALESCE(NULLIF(current_setting('app.customer_to', true), ''), 'CUST00100')
      AND cu.customer_id IN (SELECT customer_id FROM months)
),
sweepers AS (   -- customers whose salary is moved on monthly: their spending happens elsewhere
    SELECT c.customer_id
    FROM cls c, params p
    WHERE c.flow = 'transfer' AND c.tx_date BETWEEN p.win_start AND p.win_end
    GROUP BY 1
    HAVING count(DISTINCT date_trunc('month', c.tx_date)) >= 4
),
cust_metric AS (   -- every customer gets every metric; no spending means 0
    SELECT k.customer_id, k.age_band, k.area3, k.city2, ml.metric,
           COALESCE(s.eur, 0) / m.n_months AS value_month,
           (k.customer_id NOT IN (SELECT customer_id FROM sweepers)) AS comparable
    FROM cust k
    JOIN months m USING (customer_id)
    CROSS JOIN metric_list ml
    LEFT JOIN sums s ON s.customer_id = k.customer_id AND s.metric = ml.metric
),
mart_ready AS (   -- true only when the build for this "today" is complete: a flag row for every customer.
                 -- Each batch writes all three mart tables in one transaction, so complete flags mean
                 -- complete marts; a first or stopped build falls back to the range instead.
    SELECT (SELECT count(*) FROM metric_peer_flags f, params p WHERE f.as_of = p.today)
           >= (SELECT count(*) FROM customers) AS ok
),
mart_flags AS (   -- mart customers in the age bands of the customers in the range: every peer level
                 -- below "all" stays inside one age band, and "all" is not needed with the marts
    SELECT f.*
    FROM metric_peer_flags f, params p
    WHERE f.as_of = p.today AND f.age_band IN (SELECT age_band FROM cust)
      AND (SELECT ok FROM mart_ready)
),
mart_sums AS (
    SELECT m.customer_id, m.metric, sum(m.value_eur) AS eur
    FROM metric_customer_month m
    JOIN mart_flags f ON f.customer_id = m.customer_id AND f.as_of = m.as_of
    GROUP BY 1, 2
),
population AS (   -- everyone a customer can be compared with
    SELECT f.customer_id, f.age_band, f.area3, f.city2, f.comparable, ml.metric,
           COALESCE(ms.eur, 0) / f.n_months AS value_month
    FROM mart_flags f
    CROSS JOIN metric_list ml
    LEFT JOIN mart_sums ms ON ms.customer_id = f.customer_id AND ms.metric = ml.metric
    UNION ALL
    SELECT cm.customer_id, cm.age_band, cm.area3, cm.city2, cm.comparable, cm.metric, cm.value_month
    FROM cust_metric cm
    WHERE NOT (SELECT ok FROM mart_ready)
),
level_list AS (   -- with the marts every age band has at least 121 comparable customers, so "all" is only used
                 -- by the range-only fallback
    SELECT v.peer_level, v.level_rank
    FROM (VALUES ('age_band+area3', 1), ('age_band+city', 2), ('age_band', 3), ('all', 4)) AS v (peer_level, level_rank)
    WHERE v.peer_level <> 'all' OR NOT (SELECT ok FROM mart_ready)
),
peers AS (   -- comparable members only, at every level; sweepers never enter a peer group
    SELECT po.customer_id, po.metric, po.value_month, l.peer_level,
           CASE l.peer_level WHEN 'age_band+area3' THEN po.age_band || ' ' || po.area3
                             WHEN 'age_band+city'  THEN po.age_band || ' ' || po.city2
                             WHEN 'age_band'       THEN po.age_band
                             ELSE 'all' END AS peer_group
    FROM population po CROSS JOIN level_list l
    WHERE po.comparable
),
group_stats AS (   -- median/p25/p75 of the whole group, the customer included (one value among 21+ moves
                  -- them little); peer_n and percentile count only the other members
    SELECT peer_level, peer_group, metric, count(*) AS group_n,
           percentile_cont(0.25) WITHIN GROUP (ORDER BY value_month) AS p25,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY value_month) AS p50,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY value_month) AS p75
    FROM peers
    GROUP BY 1, 2, 3
),
in_peers AS (SELECT DISTINCT customer_id FROM population WHERE comparable),
you AS (   -- the customers in the range at every level, with the size of their group minus themselves
    SELECT cm.customer_id, cm.metric, cm.value_month, cm.comparable, l.peer_level, l.level_rank,
           CASE l.peer_level WHEN 'age_band+area3' THEN cm.age_band || ' ' || cm.area3
                             WHEN 'age_band+city'  THEN cm.age_band || ' ' || cm.city2
                             WHEN 'age_band'       THEN cm.age_band
                             ELSE 'all' END AS peer_group,
           (ip.customer_id IS NOT NULL) AS self_in_peers
    FROM cust_metric cm
    CROSS JOIN level_list l
    LEFT JOIN in_peers ip ON ip.customer_id = cm.customer_id
),
sized AS (
    SELECT y.*, gs.p25, gs.p50, gs.p75,
           COALESCE(gs.group_n, 0) - CASE WHEN y.self_in_peers AND gs.group_n IS NOT NULL THEN 1 ELSE 0 END AS peer_n
    FROM you y
    LEFT JOIN group_stats gs USING (peer_level, peer_group, metric)
),
chosen AS (   -- most specific level whose group is big enough; if none is, the coarsest level (not shown)
    SELECT DISTINCT ON (s.customer_id, s.metric) s.*
    FROM sized s
    ORDER BY s.customer_id, s.metric,
             CASE WHEN s.peer_n >= COALESCE(NULLIF(current_setting('app.peer_min_n', true), ''), '20')::int
                  THEN s.level_rank ELSE 100 - s.level_rank END
),
less AS (   -- other peers in the chosen group who spend less (one join on the group key)
    SELECT ch.customer_id, ch.metric,
           count(q.customer_id) FILTER (WHERE q.customer_id <> ch.customer_id AND q.value_month < ch.value_month) AS n_less
    FROM chosen ch
    LEFT JOIN peers q ON q.peer_level = ch.peer_level AND q.peer_group = ch.peer_group AND q.metric = ch.metric
    GROUP BY 1, 2
),
final AS (   -- statistics are only given when the group is big enough and the customer is comparable
    SELECT ch.*, ls.n_less,
           (ch.comparable AND ch.peer_n >= COALESCE(NULLIF(current_setting('app.peer_min_n', true), ''), '20')::int) AS shown
    FROM chosen ch
    JOIN less ls USING (customer_id, metric)
)
SELECT f.customer_id,
       f.metric,
       round(f.value_month::numeric, 2)                                         AS you_month_eur,
       CASE WHEN f.shown THEN round(f.p50::numeric, 2) END                      AS peer_median_month_eur,
       CASE WHEN f.shown THEN round(f.p25::numeric, 2) END                      AS peer_p25_month_eur,
       CASE WHEN f.shown THEN round(f.p75::numeric, 2) END                      AS peer_p75_month_eur,
       CASE WHEN f.shown THEN round(100.0 * f.n_less / f.peer_n, 0) END         AS percentile,   -- share of peers spending less
       CASE WHEN f.shown THEN round(100 * (f.value_month / NULLIF(f.p50, 0) - 1)::numeric, 1) END AS vs_median_pct,
       f.shown,
       f.comparable,
       f.peer_level,
       f.peer_group,
       f.peer_n,
       CASE WHEN (SELECT ok FROM mart_ready) THEN 'marts' ELSE 'range' END     AS peer_source,
       p.win_start AS period_start,
       p.win_end   AS period_end
FROM final f
CROSS JOIN params p
JOIN metric_list ml ON ml.metric = f.metric
ORDER BY f.customer_id, ml.ord;
