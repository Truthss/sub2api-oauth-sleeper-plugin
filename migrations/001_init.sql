CREATE TABLE IF NOT EXISTS plugin_oauth_sleeper_settings (
    id BIGINT PRIMARY KEY DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    threshold_percent DECIMAL(8,4) NOT NULL DEFAULT 90,
    scan_interval_seconds INTEGER NOT NULL DEFAULT 60,
    max_sleep_per_scan INTEGER NOT NULL DEFAULT 3,
    include_openai BOOLEAN NOT NULL DEFAULT TRUE,
    include_anthropic BOOLEAN NOT NULL DEFAULT TRUE,
    last_scan_at TIMESTAMPTZ,
    last_scan_scanned INTEGER NOT NULL DEFAULT 0,
    last_scan_triggered INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT plugin_oauth_sleeper_single_row CHECK (id = 1)
);

ALTER TABLE plugin_oauth_sleeper_settings
ADD COLUMN IF NOT EXISTS max_sleep_per_scan INTEGER NOT NULL DEFAULT 3;

INSERT INTO plugin_oauth_sleeper_settings (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS plugin_oauth_sleeper_events (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL,
    account_name TEXT,
    platform TEXT NOT NULL,
    window_name TEXT NOT NULL,
    utilization_percent DECIMAL(8,4) NOT NULL,
    threshold_percent DECIMAL(8,4) NOT NULL,
    reset_at TIMESTAMPTZ NOT NULL,
    previous_rate_limit_reset_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plugin_oauth_sleeper_events_created_at
ON plugin_oauth_sleeper_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_plugin_oauth_sleeper_events_account_id
ON plugin_oauth_sleeper_events(account_id);

CREATE TABLE IF NOT EXISTS plugin_oauth_sleeper_whitelist (
    account_id BIGINT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plugin_oauth_sleeper_whitelist_created_at
ON plugin_oauth_sleeper_whitelist(created_at DESC);
