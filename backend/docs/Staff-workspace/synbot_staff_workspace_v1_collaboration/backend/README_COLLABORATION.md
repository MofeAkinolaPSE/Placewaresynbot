# Collaboration + Activity v1

## Request lifecycle
`draft -> sent -> acknowledged -> in_progress -> responded -> closed`

Cancellation and reopening are supported through the service transition rules.

## API
- `GET /api/v1/requests`
- `POST /api/v1/requests`
- `GET /api/v1/requests/{id}`
- `POST /api/v1/requests/{id}/acknowledge`
- `POST /api/v1/requests/{id}/start`
- `POST /api/v1/requests/{id}/respond`
- `POST /api/v1/requests/{id}/close`
- `POST /api/v1/requests/{id}/cancel`
- `POST /api/v1/requests/{id}/reopen`
- `GET /api/v1/requests/{id}/messages`
- `POST /api/v1/requests/{id}/messages`
- `GET /api/v1/requests/{id}/activity`
- `GET /api/v1/tasks/{id}/activity`

Task create/update/transition operations now append entries to `staff_task_activity`.

## Security
The request repository only returns requests where the authenticated staff member is the requester or recipient and the organisation matches. Company filtering is applied when a company context is present.

The existing authentication seam is intentionally retained for integration with Synbot's real JWT/session layer.
