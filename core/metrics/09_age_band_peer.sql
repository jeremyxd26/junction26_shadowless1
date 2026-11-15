-- Metric 9: the customer's age band in the whole synthetic dataset, beside the peer comparison (#883).
-- The window and the monthly average are those of 06_peer_benchmark.sql (docs/design/metrics.md, section 6).
--
-- Inputs (session settings, all optional):
--   app.demo_today     "today": the as_of of the marts that are read      (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive         (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive           (default CUST00100)
--   app.band_min_n     smallest age band whose medians may be shown       (default 30)
-- Reads only the marts built by core/marts/build.py for as_of = today (metric_peer_flags and
-- metric_customer_month, the population of 06) and customers.age; it never reads transactions. Without a
-- complete build for this today (the same check as 06) it returns no rows.
-- Bands, from customers.age: 18-24, 25-34, 35-44, 45-54, 55-64, 65+.
-- Measures: per customer, the monthly average over the last 6 complete months (the window's spending divided
-- by the months with history in it, as 06), then the median over the customers of the band:
--   regular_essentials, unexpected_necessities, everyday_spending   the three baskets (02_baskets.sql)
--   ordinary_spending   the spend flow (spend_total of 06): all outgoing spending except Invest Deposit and
--                       Salary Sweep; income is never part of it
-- Every customer of the build is counted, one with a monthly Salary Sweep too: the cohort is everyone of the
-- band in the dataset. One row per band; customer_id is set only on the row of the band of the customer in the
-- range. A band of fewer than app.band_min_n customers is not shown: shown = false and no medians.

SET statement_timeout = '60s';

WITH
params AS (
    SELECT today,
           (date_trunc('month', today + 1) - interval '6 months')::date AS win_start,
           (date_trunc('month', today + 1) - interval '1 day')::date    AS win_end,
           COALESCE(NULLIF(current_setting('app.band_min_n', true), ''), '30')::int AS min_n
    FROM (SELECT COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date AS today) p
),
mart_ready AS (   -- as in 06: true only when the build for this "today" holds a flag row for every customer
    SELECT (SELECT count(*) FROM metric_peer_flags f, params p WHERE f.as_of = p.today)
           >= (SELECT count(*) FROM customers) AS ok
),
band_list (age_band, age_from, age_to, ord) AS (
    VALUES ('18-24', 18, 24, 1), ('25-34', 25, 34, 2), ('35-44', 35, 44, 3), ('45-54', 45, 54, 4),
           ('55-64', 55, 64, 5), ('65+', 65, NULL, 6)
),
measure_list (measure, metric) AS (
    VALUES ('regular_essentials', 'regular_essentials'), ('unexpected_necessities', 'unexpected_necessities'),
           ('everyday_spending', 'everyday_spending'), ('ordinary_spending', 'spend_total')
),
members AS (   -- every customer of the build, in the band of their age
    SELECT f.customer_id, f.n_months, b.age_band
    FROM metric_peer_flags f
    JOIN params p ON f.as_of = p.today
    JOIN customers cu ON cu.customer_id = f.customer_id
    JOIN band_list b ON cu.age >= b.age_from AND (b.age_to IS NULL OR cu.age <= b.age_to)
    WHERE (SELECT ok FROM mart_ready)
),
sums AS (   -- the window's spending of each measure; the marts hold the 6 complete months of the window only
    SELECT m.customer_id, m.metric, sum(m.value_eur) AS eur
    FROM metric_customer_month m
    JOIN params p ON m.as_of = p.today
    WHERE m.metric IN (SELECT metric FROM measure_list)
      AND (SELECT ok FROM mart_ready)
    GROUP BY 1, 2
),
per_customer AS (   -- every member gets every measure; no spending means 0
    SELECT mb.age_band, mb.customer_id, ml.measure, COALESCE(s.eur, 0) / mb.n_months AS value_month
    FROM members mb
    CROSS JOIN measure_list ml
    LEFT JOIN sums s ON s.customer_id = mb.customer_id AND s.metric = ml.metric
),
band_stats AS (
    SELECT age_band,
           count(DISTINCT customer_id) AS cohort_size,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY value_month)
               FILTER (WHERE measure = 'regular_essentials')     AS p50_regular_essentials,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY value_month)
               FILTER (WHERE measure = 'unexpected_necessities') AS p50_unexpected_necessities,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY value_month)
               FILTER (WHERE measure = 'everyday_spending')      AS p50_everyday_spending,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY value_month)
               FILTER (WHERE measure = 'ordinary_spending')      AS p50_ordinary_spending
    FROM per_customer
    GROUP BY age_band
),
you AS (   -- the band of the customer in the range
    SELECT cu.customer_id, b.age_band
    FROM customers cu
    JOIN band_list b ON cu.age >= b.age_from AND (b.age_to IS NULL OR cu.age <= b.age_to)
    WHERE cu.customer_id >= COALESCE(NULLIF(current_setting('app.customer_from', true), ''), 'CUST00000')
      AND cu.customer_id <  COALESCE(NULLIF(current_setting('app.customer_to', true), ''), 'CUST00100')
)
SELECT y.customer_id,
       b.age_band,
       COALESCE(bs.cohort_size, 0)                                                   AS cohort_size,
       (COALESCE(bs.cohort_size, 0) >= p.min_n)                                      AS shown,
       CASE WHEN bs.cohort_size >= p.min_n THEN round(bs.p50_regular_essentials::numeric, 2) END
                                                                                     AS median_regular_essentials_month_eur,
       CASE WHEN bs.cohort_size >= p.min_n THEN round(bs.p50_unexpected_necessities::numeric, 2) END
                                                                                     AS median_unexpected_necessities_month_eur,
       CASE WHEN bs.cohort_size >= p.min_n THEN round(bs.p50_everyday_spending::numeric, 2) END
                                                                                     AS median_everyday_spending_month_eur,
       CASE WHEN bs.cohort_size >= p.min_n THEN round(bs.p50_ordinary_spending::numeric, 2) END
                                                                                     AS median_ordinary_spending_month_eur,
       p.win_start                                                                   AS period_start,
       p.win_end                                                                     AS period_end
FROM band_list b
CROSS JOIN params p
LEFT JOIN band_stats bs USING (age_band)
LEFT JOIN you y USING (age_band)
WHERE (SELECT ok FROM mart_ready)
ORDER BY b.ord, y.customer_id;
