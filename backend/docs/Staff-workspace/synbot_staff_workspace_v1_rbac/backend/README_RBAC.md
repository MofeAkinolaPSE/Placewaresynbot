# Synbot Staff Workspace — RBAC v1

## Security model

Access is resolved server-side from `staff_company_memberships.role_id -> roles -> role_permissions -> permissions`.

The React company switcher is only context selection; it is never an authorization mechanism.

### Scope

Every authenticated request must belong to an active staff membership. A selected company must be an active membership for that staff member. Write operations require an explicit company context.

### Permission format

Permissions are represented as `resource:action`, for example:

- `task:view`
- `task:create`
- `task:assign`
- `task:complete`
- `request:view`
- `request:create`
- `request:respond`
- `team:view`
- `time:start`
- `progress:view`

Use `require_permission("task", "create", write=True)` in route dependencies.

### Integration

Replace `get_current_staff()` in `app/core/auth.py` with the existing Synbot JWT/session resolver. Do not pass staff identity from arbitrary frontend input.

### Access inspection

`GET /api/v1/access/me` returns the current staff member's resolved company scope and effective permissions. This endpoint is useful for bootstrapping the React workspace.
