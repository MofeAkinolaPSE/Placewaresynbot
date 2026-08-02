"""
config.py — Bridge service configuration.

All values come from environment variables, loaded from .env by python-dotenv.

Security note
-------------
.env holds the shared API key in plaintext. On Windows that file MUST be
ACL-restricted to the service account — see INSTALL.md, which ships an icacls
command for this. Validators below refuse to start with obviously unsafe
values (empty or default API key), because a bridge that silently accepts a
placeholder secret is worse than one that fails loudly at boot.
"""
from __future__ import annotations

import logging
import os
import sys
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


def _env_file_path() -> str:
    """
    Locate .env beside the executable (frozen) or beside this file (source).

    A frozen build must read the operator's .env from next to the .exe — the
    one bundled at build time (if any) would be stale and unreachable.
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, ".env")


load_dotenv(_env_file_path())

logger = logging.getLogger("bridge.config")

#: Placeholder values shipped in .env.example. Refused at startup.
_PLACEHOLDER_SECRETS = {
    "REPLACE_WITH_A_STRONG_RANDOM_SECRET",
    "REPLACE_WITH_SAME_KEY_AS_SAGE_BRIDGE_WEBHOOK_SECRET",
    "placeware-bridge-dev-key-2026",
    "changeme",
    "secret",
    "",
}


class Settings(BaseSettings):
    # ── API security ─────────────────────────────────────────────────────────
    BRIDGE_API_KEY: str = Field(
        ..., description="Shared API key required on every request to this bridge"
    )

    # ── Sage company file ────────────────────────────────────────────────────
    SAGE_COMPANY_PATH: str = Field(
        default="C:\\PLACEHOLDER\\SageCompany\\",
        description="Absolute path to the Sage 50 company data folder (.DAT files)",
    )
    SAGE_API_DLL_PATH: str = Field(
        default="C:\\Program Files (x86)\\Sage\\Peachtree\\API\\Sage.Peachtree.API.dll",
        description="Absolute path to Sage.Peachtree.API.dll",
    )

    # ── Pervasive ODBC ───────────────────────────────────────────────────────
    SAGE_ODBC_DSN: str = Field(
        default="PervasiveSage50",
        description="ODBC DSN name for the Sage company Pervasive database",
    )
    SAGE_ODBC_CONN_STR: str = Field(
        default="", description="Full pyodbc connection string (overrides DSN)"
    )
    ODBC_TIMEOUT_SECONDS: int = Field(
        default=30, ge=5, le=300,
        description="ODBC connect/query timeout. Pervasive on old hardware is slow.",
    )

    # ── Bridge HTTP server ───────────────────────────────────────────────────
    BRIDGE_HOST: str = Field(default="0.0.0.0", description="Bind address")
    BRIDGE_PORT: int = Field(default=7070, ge=1, le=65535)

    #: Comma-separated origins allowed by CORS. The original used "*".
    BRIDGE_CORS_ORIGINS: str = Field(
        default="",
        description="Allowed CORS origins, comma-separated. Empty = none (correct "
                    "for a server-to-server bridge with no browser client).",
    )
    #: OpenAPI docs are off by default — they expose the full API surface
    #: unauthenticated on the LAN. Turn on temporarily during setup.
    BRIDGE_ENABLE_DOCS: bool = Field(
        default=False, description="Expose /docs and /redoc (setup/debug only)"
    )

    # ── SynBot webhook ───────────────────────────────────────────────────────
    SYNBOT_WEBHOOK_URL: str = Field(
        default="", description="SynBot endpoint receiving Sage events"
    )
    SYNBOT_WEBHOOK_KEY: str = Field(
        default="", description="Shared secret SynBot expects on incoming webhooks"
    )

    # ── TLS ──────────────────────────────────────────────────────────────────
    BRIDGE_CA_CERT_PATH: str = Field(
        default="", description="CA/cert PEM path for HTTPS verification"
    )
    BRIDGE_INSECURE_SKIP_VERIFY: bool = Field(
        default=False,
        description="Skip TLS verification. DIAGNOSTICS ONLY — logs a warning "
                    "on every startup and every client construction.",
    )

    # ── Watcher ──────────────────────────────────────────────────────────────
    WATCHER_POLL_SECONDS: int = Field(
        default=30, ge=5, le=3600,
        description="How often to stat .DAT files for changes",
    )
    WATCHER_FULL_SCAN_SECONDS: int = Field(
        default=300, ge=30, le=86400,
        description="Run a full invoice scan at least this often, regardless of "
                    "mtime. This is the safety net for Pervasive's unreliable "
                    "mtime updates — do not disable it.",
    )
    WATCHER_SCAN_PAGE_SIZE: int = Field(
        default=100, ge=10, le=1000,
        description="Invoices per scan page. Small keeps memory flat on Win7.",
    )
    WATCHER_MAX_PAGES_PER_TICK: int = Field(
        default=20, ge=1, le=1000,
        description="Cap pages per tick so a first-run backfill cannot monopolise "
                    "the machine. Remaining pages continue on the next tick.",
    )

    # ── Outbox / retry ───────────────────────────────────────────────────────
    OUTBOX_DB_PATH: str = Field(
        default="data/outbox.db",
        description="SQLite file holding pending events and watermarks. Back this "
                    "up — it is the durability guarantee.",
    )
    SENDER_POLL_SECONDS: int = Field(default=5, ge=1, le=300)
    SENDER_BATCH_SIZE: int = Field(default=25, ge=1, le=500)
    SENDER_TIMEOUT_SECONDS: int = Field(default=30, ge=5, le=300)
    RETRY_MAX_ATTEMPTS: int = Field(
        default=20, ge=1, le=100,
        description="Attempts before an event is parked as failed. With the "
                    "defaults below this spans ~10h of wall clock, so an "
                    "overnight or weekend-start outage recovers on its own. "
                    "Verified by tests/test_sync_guarantees.py.",
    )
    RETRY_BASE_SECONDS: float = Field(default=2.0, ge=0.1, le=60.0)
    RETRY_MAX_DELAY_SECONDS: float = Field(
        default=3600.0, ge=1.0, le=86400.0,
        description="Ceiling on a single backoff interval (1h).",
    )
    OUTBOX_RETAIN_SENT_DAYS: int = Field(
        default=30, ge=1, le=3650,
        description="Delete delivered events older than this. Pending and failed "
                    "events are never purged.",
    )

    # ── Logging ──────────────────────────────────────────────────────────────
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE: str = Field(
        default="logs/sage_bridge.log",
        description="Log path. Relative paths resolve against the bridge "
                    "directory, not the service CWD (which is system32).",
    )
    LOG_MAX_BYTES: int = Field(
        default=5_000_000, ge=100_000,
        description="Rotate at this size. The original never rotated and would "
                    "eventually fill the disk.",
    )
    LOG_BACKUP_COUNT: int = Field(default=5, ge=1, le=50)

    # ── Mock mode ────────────────────────────────────────────────────────────
    SAGE_MOCK: bool = Field(
        default=False,
        description="Return mock data instead of hitting Pervasive/SDK.",
    )

    # ── validators ───────────────────────────────────────────────────────────

    @field_validator("BRIDGE_API_KEY")
    @classmethod
    def _reject_placeholder_key(cls, v: str) -> str:
        if v.strip() in _PLACEHOLDER_SECRETS:
            raise ValueError(
                "BRIDGE_API_KEY is unset or still a placeholder. Generate one "
                "with:  python -c \"import secrets;print(secrets.token_urlsafe(32))\"  "
                "and set the SAME value as SAGE_BRIDGE_KEY in SynBot's backend/.env."
            )
        if len(v.strip()) < 16:
            raise ValueError("BRIDGE_API_KEY must be at least 16 characters.")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError("LOG_LEVEL must be one of {}".format(sorted(allowed)))
        return upper

    class Config:
        # Absolute so a frozen build reads the operator's .env next to the .exe
        # rather than resolving it against the service's CWD (system32).
        env_file = _env_file_path()
        env_file_encoding = "utf-8"


def app_dir() -> str:
    """
    The directory that writable, operator-owned files live beside.

    Two very different cases:

    * **Running from source** — the directory containing this file.
    * **Running as a PyInstaller .exe** — the directory containing the .exe.
      NOT ``__file__``, which under a frozen build points inside the temporary
      extraction directory (``sys._MEIPASS``). That directory is wiped when the
      process exits, so anchoring there would put the outbox database somewhere
      that is destroyed on every restart — silently losing every undelivered
      invoice, which is precisely what the outbox exists to prevent.

    Also correct under NSSM, whose service CWD is C:\\Windows\\system32.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_relative(path: str) -> str:
    """Resolve a relative path against app_dir(). Absolute paths pass through."""
    if os.path.isabs(path):
        return path
    return os.path.join(app_dir(), path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.OUTBOX_DB_PATH = _resolve_relative(settings.OUTBOX_DB_PATH)
    settings.LOG_FILE = _resolve_relative(settings.LOG_FILE)
    return settings
