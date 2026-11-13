-- Metric 7: grocery store price index (customer-normalised, two-way fixed effects) and the estimated
-- saving from switching store.  Definition: docs/design/metrics.md, section 7.
--
-- Inputs (session settings, all optional):
--   app.demo_today     "today"; no transaction after it is read        (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive        (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive          (default CUST00100)
-- Model: ln(ticket) = a_customer + b_merchant + e, over grocery card purchases of the last 365 days,
-- fitted by alternating means on customer x merchant cells (sufficient statistics n, sum y, sum y^2),
-- so the full-population version can run on a small precomputed cell table (metrics.md).
-- PROTOTYPE SCOPE: only customers inside the range shape the index.
-- Two result sets: (1) one row per merchant, (2) one row per customer with the switch estimate.
-- The data has ticket totals, not item prices: the index mixes price level and basket size.
-- Uses one temporary table in the session (dropped at the end); nothing is written to shared tables.

SET statement_timeout = '60s';

DROP TABLE IF EXISTS pg_temp.store_cells;

CREATE TEMP TABLE store_cells AS
WITH params AS (
    SELECT COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date AS today
),
g AS (   -- grocery card purchases of the last 365 days, log ticket
    SELECT t.customer_id, t.merchant_id, t.mcc, -t.amount_eur AS ticket, ln(-t.amount_eur) AS y
    FROM transactions t, params p
    WHERE t.customer_id >= COALESCE(NULLIF(current_setting('app.customer_from', true), ''), 'CUST00000')
      AND t.customer_id <  COALESCE(NULLIF(current_setting('app.customer_to', true), ''), 'CUST00100')
      AND t.tx_date <= COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date
      AND t.tx_date >  p.today - 365
      AND t.category = 'Groceries' AND t.merchant_id IS NOT NULL AND t.amount_eur < 0
)
SELECT customer_id, merchant_id, max(mcc) AS mcc, count(*) AS n, sum(y) AS sy, sum(y * y) AS syy,
       sum(ticket) AS spend_eur
FROM g
GROUP BY 1, 2;

DROP TABLE IF EXISTS pg_temp.store_index;

CREATE TEMP TABLE store_index AS
WITH c AS (SELECT * FROM store_cells),
-- Alternating means, starting from b = 0. Five rounds; the last column reports convergence.
a1 AS (SELECT customer_id, sum(sy) / sum(n) AS a FROM c GROUP BY 1),
b1 AS (SELECT merchant_id, sum(sy - n * a) / sum(n) AS b FROM c JOIN a1 USING (customer_id) GROUP BY 1),
a2 AS (SELECT customer_id, sum(sy - n * b) / sum(n) AS a FROM c JOIN b1 USING (merchant_id) GROUP BY 1),
b2 AS (SELECT merchant_id, sum(sy - n * a) / sum(n) AS b FROM c JOIN a2 USING (customer_id) GROUP BY 1),
a3 AS (SELECT customer_id, sum(sy - n * b) / sum(n) AS a FROM c JOIN b2 USING (merchant_id) GROUP BY 1),
b3 AS (SELECT merchant_id, sum(sy - n * a) / sum(n) AS b FROM c JOIN a3 USING (customer_id) GROUP BY 1),
a4 AS (SELECT customer_id, sum(sy - n * b) / sum(n) AS a FROM c JOIN b3 USING (merchant_id) GROUP BY 1),
b4 AS (SELECT merchant_id, sum(sy - n * a) / sum(n) AS b FROM c JOIN a4 USING (customer_id) GROUP BY 1),
a5 AS (SELECT customer_id, sum(sy - n * b) / sum(n) AS a FROM c JOIN b4 USING (merchant_id) GROUP BY 1),
b5 AS (SELECT merchant_id, sum(sy - n * a) / sum(n) AS b FROM c JOIN a5 USING (customer_id) GROUP BY 1),
resid AS (   -- residual sum of squares per merchant from the cell sums
    SELECT c.merchant_id, sum(c.syy - 2 * (a5.a + b5.b) * c.sy + c.n * (a5.a + b5.b) ^ 2) AS ss
    FROM c JOIN a5 USING (customer_id) JOIN b5 USING (merchant_id)
    GROUP BY 1
),
dof AS (
    SELECT sum(n) - (SELECT count(DISTINCT customer_id) FROM c) - (SELECT count(DISTINCT merchant_id) FROM c) + 1 AS df,
           sum(n) AS n_all
    FROM c
),
sigma AS (SELECT sqrt(sum(r.ss) / max(d.df)) AS s FROM resid r CROSS JOIN dof d),
centre AS (   -- visit-weighted mean merchant effect, so that index 0 % = the average visit
    SELECT sum(c.n * b5.b) / sum(c.n) AS b_mean FROM c JOIN b5 USING (merchant_id)
),
m AS (
    SELECT merchant_id, max(mcc) AS mcc, sum(n) AS n_visits, count(*) AS n_customers,
           sum(spend_eur) / sum(n) AS avg_ticket_eur
    FROM c GROUP BY 1
)
SELECT m.merchant_id, m.mcc, m.n_visits, m.n_customers, m.avg_ticket_eur,
       b5.b - ce.b_mean                       AS effect,
       sg.s / sqrt(m.n_visits)                AS se,
       abs(b5.b - b4.b)                       AS last_step
FROM m
JOIN b5 USING (merchant_id)
JOIN b4 USING (merchant_id)
CROSS JOIN centre ce
CROSS JOIN sigma sg;

-- Result 1: the index per merchant (only merchants with at least 30 visits are shown to users).
SELECT merchant_id,
       mcc,
       n_visits,
       n_customers,
       round(avg_ticket_eur, 2)                                   AS avg_ticket_eur,
       round((100 * (exp(effect) - 1))::numeric, 1)               AS index_pct,
       round((100 * (exp(effect - 1.96 * se) - 1))::numeric, 1)   AS ci95_low_pct,
       round((100 * (exp(effect + 1.96 * se) - 1))::numeric, 1)   AS ci95_high_pct,
       (abs(effect) >= 3 * se)                                    AS differs_from_average,  -- z >= 3: about 0.2 false flags in 70 stores
       (n_visits >= 30)                                           AS shown,
       round((SELECT max(last_step) FROM store_index)::numeric, 6) AS max_last_step
FROM store_index
ORDER BY n_visits DESC, merchant_id;

-- Result 2: per customer, the main store (largest grocery spend) against the lowest-index store of
-- the same MCC that the customer already uses (3+ visits) and that has 30+ visits overall.
WITH params AS (
    SELECT COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date AS today
),
home AS (
    SELECT DISTINCT ON (customer_id) customer_id, merchant_id, mcc, spend_eur, n
    FROM store_cells
    ORDER BY customer_id, spend_eur DESC, merchant_id
),
alt AS (
    SELECT DISTINCT ON (h.customer_id)
           h.customer_id, c.merchant_id AS alt_merchant_id, si.effect AS alt_effect, si.se AS alt_se
    FROM home h
    JOIN store_cells c ON c.customer_id = h.customer_id AND c.mcc = h.mcc AND c.merchant_id <> h.merchant_id
                      AND c.n >= 3
    JOIN store_index si ON si.merchant_id = c.merchant_id AND si.n_visits >= 30
    ORDER BY h.customer_id, si.effect, c.merchant_id
),
x AS (
    SELECT h.customer_id, h.merchant_id AS home_merchant_id, h.mcc, h.n AS home_visits_12m,
           h.spend_eur / 12 AS home_spend_month_eur,
           hi.effect AS home_effect, hi.se AS home_se,
           a.alt_merchant_id, a.alt_effect, a.alt_se,
           hi.effect - a.alt_effect                        AS diff,
           sqrt(hi.se ^ 2 + a.alt_se ^ 2)                  AS diff_se
    FROM home h
    JOIN store_index hi ON hi.merchant_id = h.merchant_id
    LEFT JOIN alt a USING (customer_id)
)
SELECT customer_id,
       home_merchant_id,
       round((100 * (exp(home_effect) - 1))::numeric, 1)          AS home_index_pct,
       round(home_spend_month_eur, 2)                             AS home_spend_month_eur,
       alt_merchant_id,
       round((100 * (exp(alt_effect) - 1))::numeric, 1)           AS alt_index_pct,
       round((100 * (1 - exp(-diff)))::numeric, 1)                AS ticket_gap_pct,
       round((100 * (1 - exp(-(diff - 1.96 * diff_se))))::numeric, 1) AS ticket_gap_ci95_low_pct,
       CASE WHEN alt_merchant_id IS NULL      THEN 'no_alternative'
            WHEN diff <= 0                   THEN 'already_lowest'
            WHEN diff < 3 * diff_se          THEN 'within_noise'
            ELSE 'estimate' END                                   AS status,
       CASE WHEN alt_merchant_id IS NOT NULL AND diff >= 3 * diff_se
            THEN round((home_spend_month_eur * (1 - exp(-diff)))::numeric, 2)
            ELSE 0 END                                            AS est_saving_month_eur,
       (SELECT today - 364 FROM params)                           AS period_start,
       (SELECT today FROM params)                                 AS period_end
FROM x
ORDER BY customer_id;

DROP TABLE IF EXISTS pg_temp.store_index;
DROP TABLE IF EXISTS pg_temp.store_cells;
