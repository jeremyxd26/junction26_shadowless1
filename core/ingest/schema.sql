-- Typed schema for the S-Pankki synthetic dataset (Junction 2026, Personal Economic Trainer).
-- Re-runnable: drops and recreates the tables.

DROP TABLE IF EXISTS transactions, customers, mortgage_applications, mortgage_events CASCADE;

CREATE TABLE customers (
    customer_id  text PRIMARY KEY,
    postal_code  text NOT NULL,
    age          int  NOT NULL
);

CREATE TABLE transactions (
    id             bigserial PRIMARY KEY,
    customer_id    text           NOT NULL,
    account_id     text           NOT NULL,
    tx_date        date           NOT NULL,
    tx_at          timestamp      NOT NULL,
    category       text           NOT NULL,
    amount_eur     numeric(12, 2) NOT NULL,  -- negative = money out, positive = money in
    balance_after  numeric(14, 2),
    tx_type        text           NOT NULL,
    merchant_id    text,                     -- set only for card purchases
    mcc            text                      -- merchant category code, set only for card purchases
);

CREATE TABLE mortgage_applications (
    mortgage_customer_id   text PRIMARY KEY,
    customer_id            text NOT NULL,
    final_decision         text NOT NULL,  -- approved | rejected
    rejection_reason       text,
    property_price_eur     numeric,
    requested_loan_eur     numeric,
    equity_amount_eur      numeric,
    collateral_value_eur   numeric,
    required_monthly_income_eur numeric,
    loan_to_value          numeric
);

CREATE TABLE mortgage_events (
    id                      bigserial PRIMARY KEY,
    mortgage_customer_id    text NOT NULL,
    event_at                timestamp NOT NULL,
    event_type              text NOT NULL,
    property_id             text,
    property_type           text,
    property_price_estimate numeric,
    loan_amount             numeric,
    equity_amount           numeric,
    collateral_type         text,
    collateral_value        numeric,
    collateral_status       text,
    decision                text,
    rejection_reason        text,
    expense_type            text,
    expense_amount          numeric,
    note                    text
);
