-- Birth data/analysis/results are encrypted in the application. Events share user_events.
CREATE INDEX IF NOT EXISTS idx_user_events_fortune_time
    ON user_events(created_at, user_id) WHERE properties->>'feature'='fortune';
CREATE TABLE IF NOT EXISTS fortune_profiles (
    user_id TEXT PRIMARY KEY,
    current_profile_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS fortune_profile_versions (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES fortune_profiles(user_id) ON DELETE CASCADE,
    payload BYTEA NOT NULL,
    consent_version TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, id)
);
CREATE TABLE IF NOT EXISTS fortune_daily_results (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES fortune_profiles(user_id) ON DELETE CASCADE,
    profile_id UUID NOT NULL,
    fortune_date DATE NOT NULL,
    payload BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (user_id, profile_id) REFERENCES fortune_profile_versions(user_id, id) ON DELETE CASCADE,
    UNIQUE (user_id, profile_id, fortune_date)
);
CREATE TABLE IF NOT EXISTS fortune_form_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expected_profile_id UUID,
    expires_at TIMESTAMPTZ NOT NULL,
    opened_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_fortune_form_token_user ON fortune_form_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_fortune_form_token_expiry ON fortune_form_tokens(expires_at);
CREATE TABLE IF NOT EXISTS fortune_delete_requests (
    user_id TEXT PRIMARY KEY REFERENCES fortune_profiles(user_id) ON DELETE CASCADE,
    profile_id UUID NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
