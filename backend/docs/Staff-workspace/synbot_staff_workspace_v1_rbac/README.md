# Synbot Staff Workspace — RBAC / Multi-company v1

This package extends the Collaboration build with server-side authorization.

## Included

- `staff_company_memberships.role_id` model support
- Organization-scoped roles
- Global permission catalogue
- Role → permission resolution
- Active membership enforcement
- Company context enforcement
- Write-operation company requirement
- Sensitive task transition permission checks
- Company-context bootstrap endpoint
- Effective-access inspection endpoint

## New endpoints

`GET /api/v1/access/me`

Returns the effective permissions and selected organizational scope for the authenticated staff member.

`GET /api/v1/company-context`

Returns only active company memberships that belong to the authenticated staff member. Use this to populate the frontend company switcher.

## Important integration rule

The existing development header resolver in `app/core/auth.py` must be replaced by Synbot's real JWT/session resolver before production. The frontend must never be allowed to choose an arbitrary `staff_id` or `organization_id`.

## Permission model

Permissions use `resource:action` keys. Routes use dependencies such as:

`require_permission("task", "create", write=True)`

A selected company is valid only if it is an active membership of the authenticated staff member.

## Scope model

The membership can carry:

- company
- subsidiary
- facility
- department
- role

The current implementation establishes company-level isolation and preserves the lower-level scope on the access context. The next operational modules should apply the same context to facility/department/team queries.

## Deployment

1. Apply the existing Staff Workspace migration.
2. Create organization-scoped roles.
3. Attach permissions to roles.
4. Assign `role_id` on each active company membership.
5. Replace development auth with the real Synbot auth dependency.
6. Have React call `/company-context` after login and send the selected company through the authenticated context mechanism.
