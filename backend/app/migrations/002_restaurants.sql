-- Restaurant state and history are separate from promotion experiments.
CREATE TABLE IF NOT EXISTS restaurant_browse_states (
    user_hash TEXT PRIMARY KEY,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_restaurant_state_updated
    ON restaurant_browse_states(updated_at);

CREATE TABLE IF NOT EXISTS restaurant_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_name TEXT NOT NULL CHECK (event_name IN ('entry', 'recommendation', 'map_click')),
    user_hash TEXT,
    session_id TEXT,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_restaurant_events_time ON restaurant_events(created_at);
