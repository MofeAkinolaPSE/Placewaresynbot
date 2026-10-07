-- 132: Scheduled data backups the client downloads to their own desktop / external drive.
--
-- The server prepares a full backup on the chosen frequency (daily / weekly / monthly) into the
-- backups volume; administrators are reminded until someone downloads it. Each file is listed in
-- system_backups with who asked for it, its size, checksum and every download.

CREATE TABLE IF NOT EXISTS system_backup_settings (
    id          int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    frequency   text NOT NULL DEFAULT 'weekly' CHECK (frequency IN ('off', 'daily', 'weekly', 'monthly')),
    run_hour    int  NOT NULL DEFAULT 18 CHECK (run_hour BETWEEN 0 AND 23),
    weekday     int  NOT NULL DEFAULT 4 CHECK (weekday BETWEEN 0 AND 6),     -- 0 = Monday (Friday by default)
    month_day   int  NOT NULL DEFAULT 1 CHECK (month_day BETWEEN 1 AND 28),
    keep_last   int  NOT NULL DEFAULT 8 CHECK (keep_last BETWEEN 1 AND 60),
    updated_by  text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
INSERT INTO system_backup_settings (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS system_backups (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind               text NOT NULL CHECK (kind IN ('SCHEDULED', 'MANUAL')),
    status             text NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'READY', 'FAILED', 'DELETED')),
    format             text,
    file_name          text,
    size_bytes         bigint,
    sha256             text,
    error              text,
    requested_by       text,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,
    download_count     int NOT NULL DEFAULT 0,
    last_downloaded_at timestamptz,
    last_downloaded_by text
);
CREATE INDEX IF NOT EXISTS idx_system_backups_started ON system_backups (started_at DESC);
