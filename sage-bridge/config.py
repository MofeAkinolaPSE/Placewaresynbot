"""
config.py — Bridge service configuration.
All values come from environment variables (.env loaded by python-dotenv).
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    # ── API Security ─────────────────────────────────────────────────────────
    # Shared secret between Bridge and SynBot. Set the same value on both sides.
    BRIDGE_API_KEY: str = Field(..., description="Shared API key for all requests to this bridge")

    # ── Sage Company File ─────────────────────────────────────────────────────
    # TODO: Replace with real path when confirmed at client site.
    # Example: C:\Sage\Peachtree\Company\ClientCompanyName\
    SAGE_COMPANY_PATH: str = Field(
        default="C:\\PLACEHOLDER\\SageCompany\\",
        description="Absolute path to the Sage 50 company data folder (.DAT files live here)",
    )

    # ── Sage SDK DLL Location ─────────────────────────────────────────────────
    # Default install location for Sage 50 2013.
    SAGE_API_DLL_PATH: str = Field(
        default="C:\\Program Files (x86)\\Sage\\Peachtree\\API\\Sage.Peachtree.API.dll",
        description="Absolute path to Sage.Peachtree.API.dll",
    )

    # ── Pervasive ODBC ────────────────────────────────────────────────────────
    # DSN name as registered in Windows ODBC Data Source Administrator, OR a
    # full Pervasive connection string.
    SAGE_ODBC_DSN: str = Field(
        default="PervasiveSage50",
        description="ODBC DSN name pointing to the Sage company Pervasive database",
    )
    # Optional full connection string (overrides DSN when provided)
    SAGE_ODBC_CONN_STR: str = Field(
        default="",
        description="Full pyodbc connection string (leave blank to use DSN)",
    )

    # ── Bridge HTTP Server ────────────────────────────────────────────────────
    BRIDGE_HOST: str = Field(default="0.0.0.0", description="Bind address")
    BRIDGE_PORT: int = Field(default=7070, description="Port the bridge listens on")

    # ── SynBot Webhook ────────────────────────────────────────────────────────
    # URL SynBot exposes to receive change events from the bridge.
    SYNBOT_WEBHOOK_URL: str = Field(
        default="",
        description="SynBot endpoint to push Sage change events to (e.g. http://192.168.1.x:8000/sage/webhook)",
    )
    SYNBOT_WEBHOOK_KEY: str = Field(
        default="",
        description="Shared secret that SynBot expects on incoming webhook requests",
    )

    # ── File Watcher ──────────────────────────────────────────────────────────
    WATCHER_POLL_SECONDS: int = Field(
        default=60,
        description="How often (in seconds) to poll Sage data files for changes",
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = Field(default="INFO")

    # ── Mock Mode ─────────────────────────────────────────────────────────────
    # Set SAGE_MOCK=true in .env to run without Sage installed.
    # All ODBC and SDK calls return realistic fake data from mock_data.py.
    # Flip to false at the client site once company path + DSN are confirmed.
    SAGE_MOCK: bool = Field(
        default=False,
        description="Return mock data instead of hitting Pervasive/SDK. Must be explicitly set to true for dev/test.",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
