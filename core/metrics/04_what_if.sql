-- Metric 4: what-if savings, e.g. "dining out -20%".  Definition: docs/design/metrics.md, section 4.
--
-- Inputs (session settings, all optional):
--   app.demo_today     "today"; no transaction after it is read        (default 2026-09-30)
--   app.customer_from  first customer_id of the range, inclusive        (default CUST00000)
--   app.customer_to    end of the customer_id range, exclusive          (default CUST00100)
--   app.whatif         what to cut: category:<name> | mcc:<code>[,<code>...] | basket:<key> | merchant:<id>
--                                                                      (default category:Restaurants)
--   app.whatif_pct     how much to cut, in percent                      (default 20)
-- One row per customer with spending in the selection. The result is an estimate: it assumes the
-- coming months look like the average of the last 6 complete months, one-off spikes excluded.
-- Team-lead rule: a what-if never proposes cutting regular_essentials. Those rows of the selection
-- are left out of the baseline (shown in regular_excluded_eur); unexpected_necessities may be cut,
-- with a caveat; everyday_spending is the normal target.

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
whatif AS (
    SELECT split_part(sel, ':', 1) AS sel_kind,
           split_part(sel, ':', 2) AS sel_value,
           pct
    FROM (SELECT COALESCE(NULLIF(current_setting('app.whatif', true), ''), 'category:Restaurants') AS sel,
                 COALESCE(NULLIF(current_setting('app.whatif_pct', true), ''), '20')::numeric   AS pct) s
),
months AS (   -- months covered by the customer's history inside the window (1..6), as in 02_baskets.sql
    SELECT c.customer_id,
           GREATEST(1, LEAST(6, (extract(year FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int * 12
                                + extract(month FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int))) AS n_months
    FROM cls c, params p
    GROUP BY c.customer_id, p.win_end
),
selected AS (
    SELECT c.*
    FROM cls c, params p, whatif w
    WHERE c.flow = 'spend'
      AND c.tx_date BETWEEN p.win_start AND p.win_end
      AND CASE w.sel_kind
              WHEN 'category' THEN c.category = w.sel_value
              WHEN 'mcc'      THEN c.mcc = ANY (string_to_array(w.sel_value, ','))
              WHEN 'basket'   THEN c.basket = w.sel_value
              WHEN 'merchant' THEN c.merchant_id = w.sel_value
              ELSE false
          END
),
base AS (
    SELECT s.customer_id,
           sum(s.out_eur) FILTER (WHERE NOT s.is_one_off AND s.basket <> 'regular_essentials') AS cuttable_eur,
           sum(s.out_eur) FILTER (WHERE s.basket = 'regular_essentials')                       AS regular_excluded_eur,
           sum(s.out_eur) FILTER (WHERE s.is_one_off AND s.basket <> 'regular_essentials')     AS one_off_eur,
           count(*) FILTER (WHERE NOT s.is_one_off AND s.basket <> 'regular_essentials')       AS n_tx,
           count(*) FILTER (WHERE s.is_one_off AND s.basket <> 'regular_essentials')           AS n_one_off,
           bool_or(s.basket = 'unexpected_necessities' AND NOT s.is_one_off)                    AS has_unexpected
    FROM selected s
    GROUP BY 1
)
SELECT b.customer_id,
       w.sel_kind || ':' || w.sel_value                                         AS selection,
       w.pct                                                                    AS cut_pct,
       CASE WHEN COALESCE(b.cuttable_eur, 0) = 0 THEN 'not_offered'             -- only regular essentials or one-offs
            WHEN b.has_unexpected THEN 'estimate_with_caveat'                   -- includes needed but lumpy spending
            ELSE 'estimate' END                                                 AS status,
       round(COALESCE(b.cuttable_eur, 0) / m.n_months, 2)                       AS baseline_month_eur,
       round(COALESCE(b.cuttable_eur, 0) / m.n_months * w.pct / 100, 2)         AS saving_month_eur,
       round(COALESCE(b.cuttable_eur, 0) / m.n_months * w.pct / 100 * 7 / 30.4375, 2) AS saving_week_eur,
       round(COALESCE(b.cuttable_eur, 0) / m.n_months * w.pct / 100 * 12, 2)    AS saving_year_eur,
       b.n_tx,
       round(COALESCE(b.one_off_eur, 0), 2)                                     AS one_off_excluded_eur,
       b.n_one_off,
       round(COALESCE(b.regular_excluded_eur, 0), 2)                            AS regular_excluded_eur,
       m.n_months,
       p.win_start AS period_start,
       p.win_end   AS period_end
FROM base b
JOIN months m USING (customer_id)
CROSS JOIN whatif w
CROSS JOIN params p
ORDER BY b.customer_id;
