from fastapi import FastAPI
from app.core.config import settings
from app.api import tasks, time, workspace, notifications, collaboration, task_activity

app = FastAPI(title=settings.app_name, version='1.0.0')
app.include_router(workspace.router, prefix=settings.api_prefix)
app.include_router(tasks.router, prefix=settings.api_prefix)
app.include_router(time.router, prefix=settings.api_prefix)
app.include_router(collaboration.router, prefix="/api/v1")
app.include_router(task_activity.router, prefix="/api/v1")
app.include_router(notifications.router, prefix=settings.api_prefix)

@app.get('/health')
async def health():
    return {'status': 'ok', 'service': settings.app_name}
