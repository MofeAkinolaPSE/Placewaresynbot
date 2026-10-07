-- Frontdesk is its own department (and access role, src/roles.py).
BEGIN;
ALTER TABLE placeware_staff DROP CONSTRAINT IF EXISTS placeware_staff_department_check;
ALTER TABLE placeware_staff ADD CONSTRAINT placeware_staff_department_check CHECK (department = ANY (ARRAY[
  'Finance','Sales','Frontdesk','Operations','Procurement','Logistics','Quality','HR','Management','Admin']));
COMMIT;
