-- 7 Nov 2026: phone notifications (client, 6 Nov - "the finance team and the CFO have the app on their phones;
-- tell them when an invoice is waiting for their approval").
--
-- Web Push: a phone or laptop that turns notifications on for ACE gets the bell's action items as system
-- notifications, even with ACE closed. One row per device (browser) per login.
CREATE TABLE IF NOT EXISTS web_push_subscriptions (
    id              bigserial PRIMARY KEY,
    user_id         uuid NOT NULL REFERENCES placeware_users(id) ON DELETE CASCADE,
    endpoint        text NOT NULL UNIQUE,
    p256dh          text NOT NULL,
    auth            text NOT NULL,
    user_agent      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_sent_at    timestamptz,
    failures        int NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_web_push_user ON web_push_subscriptions (user_id);

-- The server's VAPID key pair (identifies this ACE server to the phone's push service). Made on first use;
-- kept in the database so every backend worker and every restart signs with the same key - a new key would
-- silently stop every phone that already turned notifications on.
CREATE TABLE IF NOT EXISTS web_push_keys (
    id              int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    private_der_b64 text NOT NULL,
    public_key_b64  text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
