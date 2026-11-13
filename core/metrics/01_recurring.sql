-- Metric 2: recurring bills and income cadence.  Definition: docs/design/metrics.md, section 2.
--
-- Inputs (session settings, all optional):
--   app.demo_today     "today"; no transaction after it is read        (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive        (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive          (default CUST00100)
-- One row per detected recurring series. Amounts are positive euros; direction says in or out.
-- Every read of transactions carries the customer range and the DEMO_TODAY bound directly in
-- WHERE, so the planner uses the (customer_id, ...) indexes and never scans the whole table.

SET statement_timeout = '60s';

WITH params AS (
    SELECT today,
           (date_trunc('month', today + 1) - interval '6 months')::date AS win_start,  -- first day of the 6-month window
           (date_trunc('month', today + 1) - interval '1 day')::date    AS win_end,    -- last complete month's last day
           date_trunc('month', today)::date                              AS month_start
    FROM (SELECT COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date AS today) p
),
tx AS (
    SELECT t.id, t.customer_id, t.tx_date, t.tx_at, t.category, t.tx_type, t.merchant_id, t.mcc, t.amount_eur
    FROM transactions t
    WHERE t.customer_id >= COALESCE(NULLIF(current_setting('app.customer_from', true), ''), 'CUST00000')
      AND t.customer_id <  COALESCE(NULLIF(current_setting('app.customer_to', true), ''), 'CUST00100')
      AND t.tx_date <= COALESCE(NULLIF(current_setting('app.demo_today', true), ''), '2026-09-30')::date
),
-- A series is a bill or income type (tx_type) for non-card flows, or a merchant for card purchases.
keyed AS (
    SELECT tx.*,
           CASE WHEN tx_type = 'purchase' THEN 'merchant' ELSE 'tx_type' END AS series_kind,
           CASE WHEN tx_type = 'purchase' THEN merchant_id ELSE tx_type END   AS series_key
    FROM tx
    WHERE tx_type <> 'purchase' OR merchant_id IS NOT NULL
),
monthly AS (   -- one row per series and calendar month inside the window
    SELECT k.customer_id, k.series_kind, k.series_key,
           date_trunc('month', k.tx_date)::date AS month,
           count(*)                             AS n_tx,
           sum(abs(k.amount_eur))               AS total_eur,
           min(extract(day FROM k.tx_date))::int AS first_day,
           sign(sum(k.amount_eur))::int          AS dir
    FROM keyed k, params p
    WHERE k.tx_date BETWEEN p.win_start AND p.win_end
    GROUP BY 1, 2, 3, 4
),
series AS (
    SELECT customer_id, series_kind, series_key,
           count(*)                                                        AS months_present,
           percentile_disc(0.5) WITHIN GROUP (ORDER BY n_tx)               AS tx_per_month,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY total_eur)          AS typical_month_eur,
           stddev_samp(total_eur) / NULLIF(avg(total_eur), 0)              AS cv_month,
           percentile_disc(0.5) WITHIN GROUP (ORDER BY first_day)          AS typical_day,
           sum(n_tx)                                                       AS n_tx_window,
           max(n_tx)                                                       AS max_tx_month,
           CASE WHEN sum(dir) > 0 THEN 'in' ELSE 'out' END                  AS direction
    FROM monthly
    GROUP BY 1, 2, 3
),
recurring AS (
    SELECT s.*
    FROM series s
    WHERE s.months_present >= 4                       -- present in at least 4 of the 6 complete months
      AND (s.series_kind = 'tx_type'                  -- bill and income types qualify on presence alone
           OR (s.max_tx_month = 1 AND s.cv_month <= 0.10))  -- a merchant needs one stable charge a month
),
this_month AS (   -- what each series already did in the current (possibly partial) month
    SELECT k.customer_id, k.series_key, count(*) AS n_tx, sum(abs(k.amount_eur)) AS total_eur,
           max(k.tx_date) AS last_date
    FROM keyed k, params p
    WHERE k.tx_date BETWEEN p.month_start AND p.today
    GROUP BY 1, 2
),
last_tx AS (
    SELECT DISTINCT ON (k.customer_id, k.series_key)
           k.customer_id, k.series_key, k.id AS last_tx_id, k.tx_date AS last_date, abs(k.amount_eur) AS last_amount_eur
    FROM keyed k
    ORDER BY k.customer_id, k.series_key, k.tx_at DESC, k.id DESC
),
late AS (   -- salary only: share of the last 12 salary months that paid on day 26 or later
    SELECT k.customer_id, avg((extract(day FROM k.tx_date) >= 26)::int) AS late_share_12m
    FROM keyed k, params p
    WHERE k.series_key = 'salary' AND k.tx_date > p.today - 365
    GROUP BY 1
)
SELECT r.customer_id,
       r.series_kind,
       r.series_key,
       r.direction,
       'monthly'                                        AS cadence,
       r.months_present,
       r.tx_per_month,
       round(r.typical_month_eur::numeric, 2)           AS typical_month_eur,
       round(r.cv_month::numeric, 3)                    AS cv_month,
       r.typical_day,
       l.last_date,
       l.last_amount_eur,
       l.last_tx_id,
       COALESCE(tm.n_tx, 0)                             AS n_tx_this_month,
       round(COALESCE(tm.total_eur, 0), 2)              AS paid_this_month_eur,
       CASE
           WHEN r.tx_per_month > 1 THEN 'spread'                     -- several per month: use pro rata
           WHEN tm.n_tx IS NOT NULL THEN 'done_this_month'
           WHEN extract(day FROM p.today) < r.typical_day THEN 'upcoming'
           WHEN r.direction = 'in' THEN 'late'                        -- income: still expected by month end
           WHEN extract(day FROM p.today) - r.typical_day <= 7 THEN 'late'   -- a bill a few days late
           ELSE 'skipped_this_month'                                   -- a bill over 7 days late
       END                                              AS status,
       CASE
           WHEN r.tx_per_month > 1 THEN NULL
           WHEN tm.n_tx IS NOT NULL
             OR (r.direction = 'out' AND extract(day FROM p.today) - r.typical_day > 7) THEN
               LEAST((p.month_start + interval '1 month')::date + (r.typical_day - 1),   -- next month, typical day
                     (p.month_start + interval '2 months' - interval '1 day')::date)     -- clamped to month end
           WHEN extract(day FROM p.today) < r.typical_day THEN
               LEAST(p.month_start + (r.typical_day - 1),
                     (p.month_start + interval '1 month' - interval '1 day')::date)
           WHEN r.direction = 'in' THEN
               GREATEST((p.month_start + interval '1 month' - interval '1 day')::date, p.today + 1)  -- by month end
           ELSE p.today + 1                                                                  -- late bill: due now
       END                                              AS next_expected_date,
       round(lt.late_share_12m::numeric, 2)             AS late_share_12m,
       p.win_start                                      AS period_start,
       p.win_end                                        AS period_end
FROM recurring r
CROSS JOIN params p
JOIN last_tx l ON l.customer_id = r.customer_id AND l.series_key = r.series_key
LEFT JOIN this_month tm ON tm.customer_id = r.customer_id AND tm.series_key = r.series_key
LEFT JOIN late lt ON lt.customer_id = r.customer_id AND r.series_key = 'salary'
ORDER BY r.customer_id, r.direction, r.series_kind, r.series_key;
