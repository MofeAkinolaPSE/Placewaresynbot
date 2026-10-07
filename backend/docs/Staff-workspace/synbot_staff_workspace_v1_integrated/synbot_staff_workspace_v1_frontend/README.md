# Synbot Staff Workspace — React v1

First UI vertical slice for the Staff Workspace concept.

## Included
- My Day
- My Work
- Inbox
- Team
- Progress
- Global work timer
- Task drawer
- Checklist / comments UI
- Business reference display
- API client for the FastAPI v1 endpoints
- Responsive layout

## Run

```bash
npm install
npm run dev
```

Set `VITE_API_BASE_URL` to the FastAPI API base, e.g. `http://localhost:8000/api/v1`.

The current UI includes a small demo dataset so the workspace can be reviewed before the backend is connected. Replace demo state with `api.workspace()` / `api.tasks()` during integration.
