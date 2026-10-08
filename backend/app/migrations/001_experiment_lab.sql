-- Separate protocol experiments from legacy button experiments; no data rewriting.
CREATE TABLE IF NOT EXISTS lab_experiments (
 id BIGSERIAL PRIMARY KEY, experiment_key TEXT UNIQUE NOT NULL,
 name TEXT NOT NULL, hypothesis TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('aa','ab')),
 protocol JSONB NOT NULL, config_hash TEXT NOT NULL, salt TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','running','paused','observing','ready','stopped','decided')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), started_at TIMESTAMPTZ,
 enrollment_closed_at TIMESTAMPTZ, stopped_at TIMESTAMPTZ, created_by TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS lab_one_active_scope ON lab_experiments ((1))
 WHERE status IN ('running','paused','observing');
CREATE TABLE IF NOT EXISTS lab_assignments (
 experiment_id BIGINT NOT NULL REFERENCES lab_experiments(id), user_id TEXT NOT NULL,
 variant TEXT NOT NULL CHECK(variant IN ('A','B')), assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 pre_activity_days INT NOT NULL, first_place TEXT NOT NULL, eligibility_version TEXT NOT NULL,
 PRIMARY KEY(experiment_id,user_id)
);
CREATE INDEX IF NOT EXISTS lab_assignment_user ON lab_assignments(user_id,assigned_at);
CREATE TABLE IF NOT EXISTS lab_requests (
 request_id TEXT PRIMARY KEY, experiment_id BIGINT NOT NULL REFERENCES lab_experiments(id),
 user_id TEXT NOT NULL, variant TEXT NOT NULL, route TEXT NOT NULL,
 received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), completed_at TIMESTAMPTZ,
 latency_ms DOUBLE PRECISION, error BOOLEAN, response_included BOOLEAN, error_code TEXT
);
CREATE TABLE IF NOT EXISTS lab_bundles (
 bundle_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL REFERENCES lab_requests(request_id),
 experiment_id BIGINT NOT NULL REFERENCES lab_experiments(id), user_id TEXT NOT NULL,
 planned_variant TEXT NOT NULL, rendered_policy TEXT NOT NULL, actual_card_count INT NOT NULL,
 fallback_reason TEXT, items JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS lab_analysis_runs (
 id BIGSERIAL PRIMARY KEY, experiment_id BIGINT NOT NULL REFERENCES lab_experiments(id),
 idempotency_key TEXT NOT NULL, config_hash TEXT NOT NULL, analysis_version TEXT NOT NULL,
 watermark TIMESTAMPTZ NOT NULL, result JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(experiment_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS lab_audit (
 id BIGSERIAL PRIMARY KEY, experiment_id BIGINT NOT NULL REFERENCES lab_experiments(id),
 actor TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
 details JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS lab_preview_overrides (
 user_id TEXT PRIMARY KEY, experiment_id BIGINT NOT NULL REFERENCES lab_experiments(id),
 session_id TEXT NOT NULL, variant TEXT NOT NULL CHECK(variant IN ('A','B')),
 expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS lab_requests_time ON lab_requests(experiment_id,received_at);
CREATE INDEX IF NOT EXISTS lab_bundles_time ON lab_bundles(experiment_id,created_at);
