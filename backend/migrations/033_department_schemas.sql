-- Migration: Create DepartmentSchemas for Schema Registry
CREATE TABLE IF NOT EXISTS department_schemas (
    id BIGSERIAL PRIMARY KEY,
    department TEXT NOT NULL,
    event_type TEXT NOT NULL,
    fields JSONB NOT NULL,
    created_by TEXT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    version INT NOT NULL DEFAULT 1,
    active BOOLEAN NOT NULL DEFAULT true
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_department_event_type ON department_schemas(department, event_type);
