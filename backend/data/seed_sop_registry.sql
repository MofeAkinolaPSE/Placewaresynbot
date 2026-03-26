-- Seed: SOP Registry — Placeware Nigeria (Pharmaceutical Cold-Chain Distributor)
-- Run AFTER migration 070_qms_compliance_schema.sql
-- Sourced from SOP INDEX 2024

BEGIN;

INSERT INTO sop_registry (sop_id, title, category, version, effective_from, owner_department, status, description, review_interval_days)
VALUES

-- STORAGE & HANDLING
('SOP-STR-001', 'Cold Room Temperature Monitoring Procedure', 'storage', '2.1',
 '2024-01-15', 'Quality Assurance', 'active',
 'Daily monitoring, logging and escalation protocol for all cold room temperature excursions.', 180),

('SOP-STR-002', 'Ambient Temperature Storage Guidelines', 'storage', '1.3',
 '2024-01-15', 'Warehouse', 'active',
 'Defines acceptable storage conditions for ambient-temperature pharmaceutical products.', 365),

('SOP-STR-003', 'Goods Receiving and Anti-Room Staging', 'storage', '2.0',
 '2024-03-01', 'Warehouse', 'active',
 'Procedure for receiving inbound pharmaceutical stock, staging in anti-room, and batch verification before cold room entry.', 365),

('SOP-STR-004', 'Cold Room Stacking and FIFO Procedure', 'storage', '1.2',
 '2024-01-15', 'Warehouse', 'active',
 'Pallet stacking sequence, aisle management, and FIFO rotation rules for cold storage.', 365),

('SOP-STR-005', 'Temperature Excursion Response Protocol', 'storage', '1.1',
 '2024-06-01', 'Quality Assurance', 'active',
 'Immediate response actions, quarantine protocol, and documentation requirements when temperature breach is detected.', 180),

-- QUALITY CONTROL & REGULATORY
('SOP-QC-001', 'Batch Documentation and Release Checklist', 'qc', '2.3',
 '2024-01-15', 'Quality Assurance', 'active',
 'Pre-release batch verification: NAFDAC batch numbers, expiry verification, documentation review.', 180),

('SOP-QC-002', 'NAFDAC Physical Sampling Procedure', 'qc', '1.4',
 '2024-01-15', 'Quality Assurance', 'active',
 'Protocol for NAFDAC inspector sampling, chain of custody documentation, and sample retention.', 365),

('SOP-QC-003', 'Quality Documentation Control', 'qc', '1.0',
 '2024-01-15', 'Quality Assurance', 'active',
 'Document numbering, versioning, approval, distribution and archiving standards.', 365),

('SOP-QC-004', 'Product Quarantine and Hold Procedure', 'qc', '1.2',
 '2024-01-15', 'Quality Assurance', 'active',
 'Identifies when products must be placed on quarantine hold, labelling requirements, and release criteria.', 365),

('SOP-QC-005', 'Supplier Quality Verification', 'qc', '1.0',
 '2024-04-01', 'Quality Assurance', 'active',
 'Pre-qualification audit checklist and ongoing monitoring for pharmaceutical suppliers.', 365),

-- DISTRIBUTION
('SOP-DIST-001', 'Dispatch and Delivery Authorisation', 'distribution', '2.0',
 '2024-01-15', 'Operations', 'active',
 'Pick list verification, dispatch authorisation, and proof-of-delivery documentation.', 365),

('SOP-DIST-002', 'Chain of Custody for Pharmaceutical Deliveries', 'distribution', '1.3',
 '2024-03-01', 'Operations', 'active',
 'Custody transfer procedures and signature requirements at each delivery handover point.', 365),

('SOP-DIST-003', 'Temperature-Controlled Delivery (TCD) Box Usage', 'distribution', '1.1',
 '2024-01-15', 'Operations', 'active',
 'Pre-deployment validation, pack-out procedure, temperature logger setup and return handling for TCD insulated boxes.', 180),

('SOP-DIST-004', 'Returns and Rejection Handling', 'distribution', '1.2',
 '2024-01-15', 'Quality Assurance', 'active',
 'Customer return receipt, segregation, investigation, and disposition (re-stock/quarantine/destroy) of returned products.', 365),

('SOP-DIST-005', 'Last-Mile Cold-Chain Verification', 'distribution', '1.0',
 '2024-06-01', 'Operations', 'active',
 'Protocol for downloading and reviewing temperature logger data post-delivery before records are archived.', 180),

-- WAREHOUSE OPERATIONS
('SOP-WHS-001', 'Monthly Warehouse Fumigation Schedule', 'warehouse', '1.2',
 '2024-01-15', 'Operations', 'active',
 'Approved fumigation chemical list, scheduling, pre-stock clearance, and post-fumigation re-entry clearance.', 180),

('SOP-WHS-002', 'Daily Warehouse Sanitation Checklist', 'warehouse', '1.0',
 '2024-01-15', 'Warehouse', 'active',
 'Daily cleaning schedule, vermin inspection, waste disposal, and sign-off requirements.', 365),

('SOP-WHS-003', 'Verification of Temperature Monitoring Devices', 'warehouse', '1.1',
 '2024-01-15', 'Quality Assurance', 'active',
 'Daily visual and electronic verification of all dataloggers and calibrated reference thermometers.', 180),

-- EQUIPMENT
('SOP-EQP-001', 'Cold Room Preventive Maintenance', 'equipment', '2.0',
 '2024-01-15', 'Maintenance', 'active',
 'Quarterly preventive maintenance checklist for cold room compressor, condenser, evaporator and door seals.', 180),

('SOP-EQP-002', 'Pharmaceutical Refrigerator Maintenance', 'equipment', '1.1',
 '2024-01-15', 'Maintenance', 'active',
 'Six-monthly inspection and cleaning protocol for all product storage refrigerators.', 180),

('SOP-EQP-003', 'Standby Generator Maintenance and Testing', 'equipment', '1.3',
 '2024-01-15', 'Maintenance', 'active',
 'Monthly running test, fuel level check, automatic transfer switch test, and annual servicing procedure for backup generator.', 180),

('SOP-EQP-004', 'Temperature Logger Calibration', 'equipment', '1.2',
 '2024-01-15', 'Quality Assurance', 'active',
 'Annual calibration of all TLD devices and dataloggers against NIST-traceable reference thermometer.', 180),

('SOP-EQP-005', 'UPS and Power Backup Maintenance', 'equipment', '1.0',
 '2024-06-01', 'Maintenance', 'active',
 'Quarterly battery capacity test and annual replacement schedule for UPS units in cold storage areas.', 365),

-- DEVIATION & RECALL
('SOP-DEV-001', 'Deviation Reporting and Investigation', 'deviation', '2.1',
 '2024-01-15', 'Quality Assurance', 'active',
 'Step-by-step process for detecting, classifying, investigating, and closing quality deviations including CAPA tracking.', 180),

('SOP-DEV-002', 'Corrective and Preventive Action (CAPA) Management', 'deviation', '1.2',
 '2024-01-15', 'Quality Assurance', 'active',
 'CAPA workflow: root cause analysis methods (5-Why, Fishbone), action assignment, effectiveness verification and closure.', 180),

('SOP-RCL-001', 'Product Recall Initiation and Execution', 'recall', '1.3',
 '2024-01-15', 'Quality Assurance', 'active',
 'Categories of recall (Class I/II/III), stakeholder notification matrix, NAFDAC reporting timeline, and recall effectiveness check.', 180),

('SOP-RCL-002', 'Distribution Trace for Affected Batches', 'recall', '1.1',
 '2024-01-15', 'Operations', 'active',
 'Using Sage 200 and dispatch records to trace all affected units across the distribution network.', 180),

-- HR & TRAINING
('SOP-HR-001', 'Staff Training and Competency Assessment', 'hr', '1.3',
 '2024-01-15', 'Human Resources', 'active',
 'Onboarding training matrix, periodic competency checks, and record retention for GxP training.', 365),

('SOP-HR-002', 'Personal Protective Equipment (PPE) Usage', 'hr', '1.1',
 '2024-01-15', 'Human Resources', 'active',
 'PPE type-by-role matrix, issuance, donning/doffing procedure, and inspection schedule.', 365),

('SOP-HR-003', 'Health and Safety Induction for New Staff', 'hr', '1.0',
 '2024-01-15', 'Human Resources', 'active',
 'Mandatory induction checklist covering emergency procedures, chemical handling, fire safety, and reporting obligations.', 365)

ON CONFLICT (sop_id) DO UPDATE SET
  title           = EXCLUDED.title,
  version         = EXCLUDED.version,
  effective_from  = EXCLUDED.effective_from,
  status          = EXCLUDED.status,
  description     = EXCLUDED.description,
  updated_at      = now();

COMMIT;
