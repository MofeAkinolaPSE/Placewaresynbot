-- Migration: Documents, versions and attachments
CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  description TEXT NULL,
  created_by TEXT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  approval_status TEXT NULL,
  approved_by TEXT NULL,
  approved_at TIMESTAMP WITH TIME ZONE NULL,
  current_version UUID NULL
);

CREATE TABLE IF NOT EXISTS document_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_number INT NOT NULL,
  storage_path TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NULL,
  size_bytes BIGINT NULL,
  uploaded_by TEXT NULL,
  uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  checksum TEXT NULL
);

CREATE TABLE IF NOT EXISTS document_attachments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  attached_to_table TEXT NULL,
  attached_to_id UUID NULL,
  attached_by TEXT NULL,
  attached_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);
CREATE INDEX IF NOT EXISTS idx_document_versions_document ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_document_attachments_doc ON document_attachments(document_id);
