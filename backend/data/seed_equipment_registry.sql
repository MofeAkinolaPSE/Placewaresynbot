-- Seed: Equipment Registry & Initial Maintenance Schedule — Placeware Nigeria
-- Run AFTER migration 070_qms_compliance_schema.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- Equipment Registry
-- ---------------------------------------------------------------------------
INSERT INTO equipment_registry
  (equipment_name, equipment_type, location, model, status,
   last_calibration_date, calibration_interval_days,
   last_maintenance_date, maintenance_interval_days, notes)
VALUES

-- Cold Rooms
('Cold Room A (Main Warehouse)', 'cold_room', 'Main Warehouse — Block A',
 'Danfoss AKC-45', 'active',
 '2025-06-15', 365,
 '2025-12-01', 90,
 'Primary pharmaceutical cold storage; target: 2–8°C. Capacity: 8 pallets.'),

('Cold Room B (Overflow Storage)', 'cold_room', 'Main Warehouse — Block B',
 'Danfoss AKC-45', 'active',
 '2025-06-15', 365,
 '2025-12-01', 90,
 'Secondary cold room; target: 2–8°C. Overflow and quarantine holding.'),

('Deep Freezer Bay (Vaccine Store)', 'cold_room', 'Annex Building — Bay 1',
 'Vestfrost VLS 400', 'active',
 '2025-06-15', 365,
 '2025-11-15', 90,
 'Freezer storage; target: -15 to -25°C. Vaccines and biologics only.'),

-- Pharmaceutical Refrigerators
('Pharmacy-Grade Refrigerator Unit 1', 'refrigerator', 'Dispensary Area',
 'LEC Medical PT110', 'active',
 '2025-04-10', 365,
 '2025-10-10', 180,
 'High-value item storage; 4°C setpoint.'),

('Pharmacy-Grade Refrigerator Unit 2', 'refrigerator', 'Receiving Anti-Room',
 'LEC Medical PT110', 'active',
 '2025-04-10', 365,
 '2025-10-10', 180,
 'Short-term staging for received batches pending QC release.'),

('Pharmacy-Grade Refrigerator Unit 3', 'refrigerator', 'Dispatch Staging Area',
 'Haier Medical HYC-290', 'active',
 '2025-05-20', 365,
 '2025-11-20', 180,
 'Dispatch buffer refrigerator. Loaded <2 hours before truck departure.'),

-- Temperature Monitoring Devices / Dataloggers
('Temperature Datalogger TLD-001', 'temperature_device', 'Cold Room A',
 'Sensitech TempTale 4', 'active',
 '2025-07-01', 365,
 NULL, NULL,
 'Primary cold room A datalogger. UHF enabled.'),

('Temperature Datalogger TLD-002', 'temperature_device', 'Cold Room B',
 'Sensitech TempTale 4', 'active',
 '2025-07-01', 365,
 NULL, NULL,
 'Primary cold room B datalogger.'),

('Temperature Datalogger TLD-003', 'temperature_device', 'Deep Freezer Bay',
 'Sensitech TempTale 4', 'active',
 '2025-07-01', 365,
 NULL, NULL,
 'Primary freeze-bay datalogger.'),

('Wireless Temperature Sensor WSN-001', 'temperature_device', 'Cold Room A (Remote)',
 'Elpro Libero G', 'active',
 '2025-07-01', 365,
 NULL, NULL,
 'Backup wireless sensor with GSM alert on breach.'),

('Wireless Temperature Sensor WSN-002', 'temperature_device', 'Cold Room B (Remote)',
 'Elpro Libero G', 'active',
 '2025-07-01', 365,
 NULL, NULL,
 'Backup wireless sensor for cold room B.'),

-- Reference Thermometers
('Calibrated Reference Thermometer REF-001', 'temperature_device', 'QA Laboratory',
 'Hart Scientific 1502A', 'active',
 '2025-07-01', 365,
 NULL, NULL,
 'NIST-traceable reference thermometer for datalogger calibration checks.'),

-- Generator
('Standby Diesel Generator GEN-001', 'generator', 'Generator House — Site Perimeter',
 'Perkins 50 kVA', 'active',
 NULL, NULL,
 '2026-01-05', 30,
 'Auto-start ATS. Supports cold rooms + critical outlets during PHCN outage.'),

-- UPS Units
('UPS Unit UPS-001 (Cold Room A)', 'other', 'Cold Room A — Control Panel',
 'APC Smart-UPS 3000VA', 'active',
 NULL, NULL,
 '2025-09-01', 90,
 '20-minute holdover at full load.'),

('UPS Unit UPS-002 (Server/Comms Room)', 'other', 'IT Room',
 'APC Smart-UPS 1500VA', 'active',
 NULL, NULL,
 '2025-09-01', 90,
 'Covers NAS, network switch, and alarm panel.')

ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Initial Maintenance Schedule (generated from equipment due dates)
-- ---------------------------------------------------------------------------
INSERT INTO maintenance_schedule
  (equipment_id, maintenance_type, interval_days, last_maintenance_date,
   next_maintenance_date, status)
SELECT
  e.id,
  'preventive',
  e.maintenance_interval_days,
  e.last_maintenance_date,
  COALESCE(e.last_maintenance_date, CURRENT_DATE) + e.maintenance_interval_days * INTERVAL '1 day',
  CASE
    WHEN e.last_maintenance_date IS NOT NULL
     AND e.last_maintenance_date + e.maintenance_interval_days * INTERVAL '1 day' < CURRENT_DATE
    THEN 'overdue'
    ELSE 'scheduled'
  END
FROM equipment_registry e
WHERE e.maintenance_interval_days IS NOT NULL
ON CONFLICT DO NOTHING;

-- Calibration schedules for temperature devices
INSERT INTO maintenance_schedule
  (equipment_id, maintenance_type, interval_days, last_maintenance_date,
   next_maintenance_date, status)
SELECT
  e.id,
  'calibration',
  e.calibration_interval_days,
  e.last_calibration_date,
  COALESCE(e.last_calibration_date, CURRENT_DATE) + e.calibration_interval_days * INTERVAL '1 day',
  CASE
    WHEN e.last_calibration_date IS NOT NULL
     AND e.last_calibration_date + e.calibration_interval_days * INTERVAL '1 day' < CURRENT_DATE
    THEN 'overdue'
    ELSE 'scheduled'
  END
FROM equipment_registry e
WHERE e.equipment_type = 'temperature_device'
  AND e.calibration_interval_days IS NOT NULL
ON CONFLICT DO NOTHING;

COMMIT;
