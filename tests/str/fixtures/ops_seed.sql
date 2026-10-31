-- SCRUM-20 통합 테스트용 ops 4테이블 최소 DDL + 행.
-- 백엔드 V002 (dajaba) 컬럼·타입 그대로. is_laundering·pattern_* 는 값 없이 — SELECT 안 되는지 확인.
--
-- facts_fan_in.json 기존 칸 값이 그대로 떨어지도록 시드:
--   거래 3건(id 1·2·3), 전부 inbound to 010_8000EBD30, ACH, US Dollar
--   합 42,750.50 USD (12500 + 14000 + 16250.50), period 2022-09-02 00:14~22:51
--   상대 3개 (020_C0000001·02·03, 전부 타행), subject entity 80062E240 Sole Proprietorship

CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.entities (
    entity_id   text PRIMARY KEY,
    entity_name text,
    entity_type text  -- CORPORATION·PARTNERSHIP·SOLE_PROPRIETORSHIP·INDIVIDUAL·COUNTRY·DIRECT (SCRUM-47)
);

CREATE TABLE IF NOT EXISTS ops.accounts (
    account_key text PRIMARY KEY,
    bank_name   text,
    entity_id   text REFERENCES ops.entities(entity_id)
);

CREATE TABLE IF NOT EXISTS ops.customer_attributes (
    entity_id        text PRIMARY KEY REFERENCES ops.entities(entity_id),
    industry         text,
    risk_level       text,
    account_purpose  text,
    onboarded_at     date,
    country_code     text
);

CREATE TABLE IF NOT EXISTS ops.transactions (
    transaction_id    bigint PRIMARY KEY,
    ts                timestamp,
    from_account_key  text,
    to_account_key    text,
    amount_paid       numeric(20, 2),
    currency_paid     text,
    amount_received   numeric(20, 2),
    currency_received text,
    payment_format    text,
    is_self_transfer  boolean,
    is_laundering     boolean,       -- 값 없이 — AI 서버 SELECT 금지(정답 라벨, docs/str/04)
    pattern_type      text,          -- 값 없이
    pattern_subtype   text           -- 값 없이
);

-- 비울 때 외래키 역순
TRUNCATE ops.transactions, ops.customer_attributes, ops.accounts, ops.entities RESTART IDENTITY CASCADE;

-- 법인
INSERT INTO ops.entities (entity_id, entity_name, entity_type) VALUES
    ('80062E240', 'Sole Proprietorship #50438', 'SOLE_PROPRIETORSHIP'),
    ('COUNTER-01', 'Counterparty #01', 'INDIVIDUAL'),
    ('COUNTER-02', 'Counterparty #02', 'INDIVIDUAL'),
    ('COUNTER-03', 'Counterparty #03', 'INDIVIDUAL');

-- 대상 계좌 + 상대 3개(전부 bank_id 020 — 대상 010 과 달라 counterparty_banks.other_bank_accounts = 3)
INSERT INTO ops.accounts (account_key, bank_name, entity_id) VALUES
    ('010_8000EBD30', 'Portugal Bank #4507', '80062E240'),
    ('020_C0000001',  'Other Bank #0020',    'COUNTER-01'),
    ('020_C0000002',  'Other Bank #0020',    'COUNTER-02'),
    ('020_C0000003',  'Other Bank #0020',    'COUNTER-03');

-- 고객 속성
INSERT INTO ops.customer_attributes (
    entity_id, industry, risk_level, account_purpose, onboarded_at, country_code
) VALUES (
    '80062E240', 'RETAIL', 'LOW', 'SALES_DEPOSIT', DATE '2021-03-14', 'PT'
);

-- 거래 3건 — 모두 inbound to 010_8000EBD30, ACH, USD
INSERT INTO ops.transactions (
    transaction_id, ts, from_account_key, to_account_key,
    amount_paid, currency_paid, amount_received, currency_received,
    payment_format, is_self_transfer
) VALUES
    (1, '2022-09-02 00:14:00', '020_C0000001', '010_8000EBD30',
     12500.00, 'US Dollar', 12500.00, 'US Dollar', 'ACH', false),
    (2, '2022-09-02 11:30:00', '020_C0000002', '010_8000EBD30',
     14000.00, 'US Dollar', 14000.00, 'US Dollar', 'ACH', false),
    (3, '2022-09-02 22:51:00', '020_C0000003', '010_8000EBD30',
     16250.50, 'US Dollar', 16250.50, 'US Dollar', 'ACH', false);
