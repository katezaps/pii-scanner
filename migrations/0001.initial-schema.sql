-- 0001.initial-schema
-- depends:
--
-- Consolidated schema.
--
-- Privacy posture on timestamps:
--   - Scan / PII-derived tables carry only ``expires_at``. We never record
--     *when* a scan happened — only that it is or is not still fresh.
--     Freshness is binary: a row exists with state=SUCCESS and
--     expires_at > now() => use it; otherwise scan again.
--   - Operator-managed resources (users, api_tokens, brokers) keep standard
--     administrative timestamps. They describe provisioning, not scanning.

-- ============================================================================
-- Enums
-- ============================================================================

CREATE TYPE scan_state AS ENUM ('RUNNING', 'SUCCESS', 'CANCELLED', 'FAILED');
CREATE TYPE scan_result_source AS ENUM ('FRESH', 'CACHE_HIT');


-- ============================================================================
-- users
-- One row per human using this deployment.
-- ============================================================================

CREATE TABLE users (
    id              uuid PRIMARY KEY,
    name            text,
    password_hash   text,
    created_at      timestamptz NOT NULL DEFAULT now()
);


-- ============================================================================
-- api_tokens
-- Bearer tokens, hashed. Plaintext is shown once at creation, never stored.
-- ============================================================================

CREATE TABLE api_tokens (
    id            uuid PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash    text NOT NULL UNIQUE,
    name          text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz,
    revoked_at    timestamptz
);

CREATE INDEX api_tokens_user_id_idx ON api_tokens(user_id);


-- ============================================================================
-- brokers
-- Seeded from brokers/brokers.json. Each (version, key)
-- pair is a complete redeclaration of a broker at that version.
-- ============================================================================

CREATE TABLE brokers (
    id          uuid PRIMARY KEY,
    version     integer NOT NULL,
    key         text NOT NULL,
    name        text NOT NULL,
    search_url  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (version, key)
);

CREATE INDEX brokers_version_idx ON brokers(version);


-- ============================================================================
-- broker_field_scans
-- Dedup cache. One row per (field_name, broker_id).
-- Failures are NOT stored. RUNNING (in-flight), SUCCESS, and CANCELLED
-- rows are persisted. CANCELLED rows appear in audit results so users
-- can see which brokers timed out or were interrupted.
-- ============================================================================

CREATE TABLE broker_field_scans (
    id              uuid PRIMARY KEY,
    field_name      text NOT NULL,
    field_type      text NOT NULL,
    broker_id       uuid NOT NULL REFERENCES brokers(id),
    state           scan_state NOT NULL,
    found           boolean NOT NULL DEFAULT false,
    message         text,
    expires_at      timestamptz NOT NULL,
    user_id         uuid REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (field_name, broker_id)
);

CREATE INDEX broker_field_scans_expires_at_idx ON broker_field_scans(expires_at);
CREATE INDEX broker_field_scans_broker_id_idx ON broker_field_scans(broker_id);
CREATE INDEX broker_field_scans_user_id_idx ON broker_field_scans(user_id);


-- ============================================================================
-- scan_executions
-- A scan submission. Each scan creates a new row. Multiple executions per
-- user are allowed. Optional human-readable name, unique per user.
-- ============================================================================

CREATE TABLE scan_executions (
    id              uuid PRIMARY KEY,
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version         integer NOT NULL,
    expires_at      timestamptz NOT NULL DEFAULT (now() + interval '30 days'),
    name            text,
    state           scan_state NOT NULL DEFAULT 'RUNNING'
);

CREATE INDEX scan_executions_user_id_expires_at_idx
    ON scan_executions(user_id, expires_at DESC);
CREATE UNIQUE INDEX scan_executions_user_name_idx
    ON scan_executions(user_id, name) WHERE name IS NOT NULL;


-- ============================================================================
-- scan_execution_results
-- Join table: which broker_field_scans rows did this execution touch, and
-- were they served fresh or from cache during the most recent run?
--
-- (execution_id, broker_field_scan_id) is the conflict target on rerun;
-- ``source`` is updated in place to reflect the latest run's path.
-- ============================================================================

CREATE TABLE scan_execution_results (
    execution_id          uuid NOT NULL REFERENCES scan_executions(id) ON DELETE CASCADE,
    broker_field_scan_id  uuid NOT NULL REFERENCES broker_field_scans(id),
    source                scan_result_source NOT NULL,
    PRIMARY KEY (execution_id, broker_field_scan_id)
);

CREATE INDEX scan_execution_results_bfs_idx
    ON scan_execution_results(broker_field_scan_id);
