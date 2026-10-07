-- Synbot Staff Workspace RBAC bootstrap helpers.
-- Run after synbot_staff_workspace_v1_migration.sql.
-- Roles are organization-scoped; create one per organization rather than a global role.

-- Example: create the standard staff role for one organization.
-- Replace :organization_id with a real UUID in your migration/deployment tooling.
--
-- INSERT INTO roles (organization_id, name, code, description)
-- VALUES (:organization_id, 'Staff', 'staff', 'Standard staff workspace permissions')
-- ON CONFLICT (organization_id, code) DO NOTHING;

-- Example: grant standard staff permissions.
--
-- INSERT INTO role_permissions (role_id, permission_id)
-- SELECT r.id, p.id
-- FROM roles r
-- JOIN permissions p ON (p.resource, p.action) IN (
--   ('task','view'), ('task','create'), ('task','update'), ('task','complete'),
--   ('request','view'), ('request','create'), ('request','respond'),
--   ('team','view'), ('time','view'), ('time','start'), ('progress','view'),
--   ('notification','manage')
-- )
-- WHERE r.organization_id = :organization_id AND r.code = 'staff'
-- ON CONFLICT DO NOTHING;

-- Example manager role can additionally receive assignment/verification/closure rights.
-- Keep this explicit so each client organization controls its own role model.
