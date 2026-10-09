"""Print one access token per role for loadtest.py (run inside the backend container, cwd /backend).

Each token belongs to a real active user so per-user pages (workspace, inbox) behave as in use;
roles with no user of their own borrow the admin account's id.
"""
import json
import sys

sys.path.insert(0, "/backend")
from src.auth_utils import create_access_token
from src.db import db

ROLES = ["sales", "frontdesk", "finance", "ops", "quality_assurance", "procurement", "hr", "management", "admin"]

users = db.table("placeware_users").select("id,roles").eq("is_active", True).execute().data or []
by_role = {}
for u in users:
    for r in u.get("roles") or []:
        by_role.setdefault(r, str(u["id"]))
fallback = by_role.get("admin") or (str(users[0]["id"]) if users else "loadtest")
print(json.dumps({r: create_access_token(by_role.get(r, fallback), [r])[0] for r in ROLES}))
