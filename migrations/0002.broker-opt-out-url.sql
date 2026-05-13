-- 0002.broker-opt-out-url
-- depends: 0001.initial-schema

CREATE TYPE opt_out_url_source AS ENUM ('GENERATED', 'SEED');

ALTER TABLE brokers ADD COLUMN opt_out_url text;
ALTER TABLE brokers ADD COLUMN opt_out_url_source opt_out_url_source;
