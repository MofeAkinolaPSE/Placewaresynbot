-- Seed: Audit Schedule 2026 — Placeware Nigeria
-- Run AFTER migration 070_qms_compliance_schema.sql

BEGIN;

INSERT INTO audit_schedule
  (audit_type, risk_level, frequency, department, month_due, year, assigned_to, status, notes)
VALUES

-- ============================================================
-- MONTHLY SELF-AUDITS (Cold Chain & Warehouse — all months)
-- ============================================================
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 1,  2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 2,  2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 3,  2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 4,  2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 5,  2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 6,  2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 7,  2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 8,  2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 9,  2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 10, 2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 11, 2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),
('Cold Chain Self Audit',    'high',   'monthly', 'Quality Assurance', 12, 2026, 'QA Officer',      'scheduled', 'Monthly temperature compliance review'),

('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          1,  2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          2,  2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          3,  2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          4,  2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          5,  2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          6,  2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          7,  2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          8,  2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          9,  2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          10, 2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          11, 2026, 'Warehouse Manager','scheduled', NULL),
('Warehouse Sanitation Audit','medium','monthly', 'Warehouse',          12, 2026, 'Warehouse Manager','scheduled', NULL),

-- ============================================================
-- QUARTERLY AUDITS (Q1=Mar, Q2=Jun, Q3=Sep, Q4=Dec)
-- ============================================================
('Quality Control Systems Audit', 'high',   'quarterly', 'Quality Assurance', 3,  2026, 'QA Manager', 'scheduled', 'SOP adherence + documentation review'),
('Quality Control Systems Audit', 'high',   'quarterly', 'Quality Assurance', 6,  2026, 'QA Manager', 'scheduled', 'SOP adherence + documentation review'),
('Quality Control Systems Audit', 'high',   'quarterly', 'Quality Assurance', 9,  2026, 'QA Manager', 'scheduled', 'SOP adherence + documentation review'),
('Quality Control Systems Audit', 'high',   'quarterly', 'Quality Assurance', 12, 2026, 'QA Manager', 'scheduled', 'SOP adherence + documentation review'),

('Distribution & Delivery Audit', 'high',   'quarterly', 'Operations',        3,  2026, 'Operations Manager', 'scheduled', 'Third-party delivery partners + TCD performance'),
('Distribution & Delivery Audit', 'high',   'quarterly', 'Operations',        6,  2026, 'Operations Manager', 'scheduled', NULL),
('Distribution & Delivery Audit', 'high',   'quarterly', 'Operations',        9,  2026, 'Operations Manager', 'scheduled', NULL),
('Distribution & Delivery Audit', 'high',   'quarterly', 'Operations',        12, 2026, 'Operations Manager', 'scheduled', NULL),

('HR & Training Compliance Audit','medium', 'quarterly', 'Human Resources',   3,  2026, 'HR Manager',         'scheduled', 'Training records + PPE compliance check'),
('HR & Training Compliance Audit','medium', 'quarterly', 'Human Resources',   6,  2026, 'HR Manager',         'scheduled', NULL),
('HR & Training Compliance Audit','medium', 'quarterly', 'Human Resources',   9,  2026, 'HR Manager',         'scheduled', NULL),
('HR & Training Compliance Audit','medium', 'quarterly', 'Human Resources',   12, 2026, 'HR Manager',         'scheduled', NULL),

('Supplier Quality Audit',        'medium', 'quarterly', 'Procurement',       3,  2026, 'QA Officer',         'scheduled', 'Supplier documentation + certifications'),
('Supplier Quality Audit',        'medium', 'quarterly', 'Procurement',       6,  2026, 'QA Officer',         'scheduled', NULL),
('Supplier Quality Audit',        'medium', 'quarterly', 'Procurement',       9,  2026, 'QA Officer',         'scheduled', NULL),
('Supplier Quality Audit',        'medium', 'quarterly', 'Procurement',       12, 2026, 'QA Officer',         'scheduled', NULL),

-- ============================================================
-- BIANNUAL AUDITS (H1=Jun, H2=Dec)
-- ============================================================
('Regulatory Compliance Audit', 'critical', 'biannual', 'Quality Assurance', 6,  2026, 'Quality Director', 'scheduled',
 'Full NAFDAC GDP compliance assessment against current guidelines'),
('Regulatory Compliance Audit', 'critical', 'biannual', 'Quality Assurance', 12, 2026, 'Quality Director', 'scheduled',
 'Full NAFDAC GDP compliance assessment against current guidelines'),

('Equipment Calibration Audit',  'high',    'biannual', 'Maintenance',       6,  2026, 'Technical Manager','scheduled',
 'Review calibration status of all temperature monitoring devices'),
('Equipment Calibration Audit',  'high',    'biannual', 'Maintenance',       12, 2026, 'Technical Manager','scheduled', NULL),

-- ============================================================
-- ANNUAL AUDITS (December)
-- ============================================================
('NAFDAC Accreditation Audit',           'critical', 'annual', 'Quality Assurance', 11, 2026, 'Quality Director',   'scheduled',
 'Annual NAFDAC facility accreditation renewal audit — full site inspection'),
('Annual Management QMS Review',         'high',     'annual', 'Management',         12, 2026, 'Managing Director',  'scheduled',
 'Comprehensive QMS effectiveness review presented to board'),
('Annual Internal GxP Gap Assessment',   'high',     'annual', 'Quality Assurance',  10, 2026, 'QA Manager',         'scheduled',
 'Benchmark current practices against WHO-GDP guidelines and NAFDAC requirements'),
('Financial & Procurement Compliance',   'medium',   'annual', 'Finance',             1, 2026, 'Finance Director',   'scheduled',
 'Annual review of procurement controls and financial compliance')

ON CONFLICT DO NOTHING;

COMMIT;
