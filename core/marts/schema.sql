-- Precomputed marts for the peer benchmark (metric 6) and the grocery store index (metric 7).
-- Design: docs/design/metrics.md, section 8. Filled by core/marts/build.py in batches of 100 customers.
-- Safe to re-run: creates only what is missing and never drops anything.
-- Every row carries as_of, the DEMO_TODAY the mart was built for; the metric files read only the
-- rows whose as_of equals their own "today".

CREATE TABLE IF NOT EXISTS metric_customer_month (
    as_of        date          NOT NULL,   -- DEMO_TODAY of the build
    customer_id  text          NOT NULL,
    month        date          NOT NULL,   -- first day of a month in the 6-complete-month window
    metric       text          NOT NULL,   -- spend_total, a basket key, or a category (Health is not stored, R9)
    value_eur    numeric(12,2) NOT NULL,   -- spend in that month, positive euros
    n_tx         int           NOT NULL,
    PRIMARY KEY (as_of, customer_id, month, metric)
);

CREATE TABLE IF NOT EXISTS metric_peer_flags (
    as_of        date    NOT NULL,
    customer_id  text    NOT NULL,
    age_band     text    NOT NULL,         -- 18-24, 25-34, ..., 75+
    area3        text    NOT NULL,         -- first 3 digits of the postal code
    city2        text    NOT NULL,         -- first 2 digits: 00 Helsinki, 01 Vantaa, 02 Espoo and Kauniainen
    comparable   boolean NOT NULL,         -- false for customers with a monthly Salary Sweep
    n_months     int     NOT NULL,         -- months of history inside the window (1..6)
    PRIMARY KEY (as_of, customer_id)
);

CREATE TABLE IF NOT EXISTS metric_grocery_cells (
    as_of        date             NOT NULL,
    customer_id  text             NOT NULL,
    merchant_id  text             NOT NULL,
    mcc          text,
    n            int              NOT NULL,   -- grocery card purchases in the 365 days up to as_of
    sy           double precision NOT NULL,   -- sum of ln(ticket)
    syy          double precision NOT NULL,   -- sum of ln(ticket)^2
    spend_eur    numeric(14,2)    NOT NULL,
    PRIMARY KEY (as_of, customer_id, merchant_id)
);

CREATE INDEX IF NOT EXISTS metric_customer_month_metric ON metric_customer_month (as_of, metric);
CREATE INDEX IF NOT EXISTS metric_grocery_cells_merchant ON metric_grocery_cells (as_of, merchant_id);
