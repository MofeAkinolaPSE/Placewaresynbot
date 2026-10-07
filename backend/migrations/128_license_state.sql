-- Licence clock-rollback detection (src/licensing/license_manager.py).
-- One row: the latest server time ever observed while a licence was installed.
CREATE TABLE IF NOT EXISTS license_state (
    id            SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    max_issued_at TIMESTAMPTZ NOT NULL,
    high_water    TIMESTAMPTZ NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
