-- Phase 4: Staff collaboration + CRM lead finder

-- Thread/channel enrichments
ALTER TABLE threads
  ADD COLUMN IF NOT EXISTS thread_type TEXT NOT NULL DEFAULT 'group',
  ADD COLUMN IF NOT EXISTS context_type TEXT,
  ADD COLUMN IF NOT EXISTS context_id TEXT,
  ADD COLUMN IF NOT EXISTS channel_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_threads_channel_key
  ON threads(channel_key)
  WHERE channel_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_threads_context
  ON threads(context_type, context_id);

CREATE TABLE IF NOT EXISTS thread_reads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  last_read_message_id UUID,
  last_read_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(thread_id, user_id)
);

CREATE TABLE IF NOT EXISTS thread_presence (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'online' CHECK (status IN ('online', 'away', 'offline')),
  last_seen_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(thread_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_thread_presence_seen ON thread_presence(thread_id, last_seen_at DESC);

-- Lead finder pipeline
CREATE TABLE IF NOT EXISTS crm_prospects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name TEXT NOT NULL,
  industry TEXT,
  region TEXT,
  contact_name TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  source TEXT,
  enrichment JSONB DEFAULT '{}'::jsonb,
  score NUMERIC(5,2) DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'sourced' CHECK (status IN ('sourced', 'enriched', 'scored', 'converted', 'archived')),
  converted_lead_id BIGINT REFERENCES leads(id) ON DELETE SET NULL,
  assigned_rep TEXT,
  next_follow_up_at TIMESTAMPTZ,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crm_prospects_status ON crm_prospects(status);
CREATE INDEX IF NOT EXISTS idx_crm_prospects_assigned_rep ON crm_prospects(assigned_rep);

CREATE TABLE IF NOT EXISTS crm_followups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  prospect_id UUID REFERENCES crm_prospects(id) ON DELETE CASCADE,
  lead_id BIGINT REFERENCES leads(id) ON DELETE CASCADE,
  assigned_to TEXT NOT NULL,
  follow_up_type TEXT NOT NULL DEFAULT 'call',
  due_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'overdue', 'cancelled')),
  notes TEXT,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crm_followups_assignee_due ON crm_followups(assigned_to, due_at);

CREATE OR REPLACE FUNCTION tg_phase4_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'crm_prospects_set_updated_at') THEN
    CREATE TRIGGER crm_prospects_set_updated_at
      BEFORE UPDATE ON crm_prospects
      FOR EACH ROW EXECUTE FUNCTION tg_phase4_set_updated_at();
  END IF;
END $$;
