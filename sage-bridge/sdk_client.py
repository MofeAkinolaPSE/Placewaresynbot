"""
sdk_client.py — Write (and structured read) access to Sage 50 via the
                official Sage.Peachtree.API.dll (.NET SDK).

This module uses pythonnet to load the Sage 50 .NET SDK assembly and
expose a thin Python wrapper around the most critical entity operations:

    Customers   — create / update
    Vendors     — create / update
    Invoices    — create sales invoice (triggers full ledger posting)
    Sales Orders — create / update
    Purchase Orders — create
    Payments    — apply customer receipts
    Journal Entries — create general journal entry
    Inventory   — read items (SDK read, safe for stock lookups)
    Company Info — read company information

IMPORTANT RUNTIME REQUIREMENTS
--------------------------------
1. This module must run on the same Windows machine where Sage 50 2013
   is installed.
2. pythonnet must target .NET Framework (not .NET Core):
       import pythonnet; pythonnet.load("netfx")
3. The Sage company file must not be exclusively locked by another process
   doing a backup at the same time (SDK handles concurrent user access fine).
4. The Windows user account running this service must have access to the
   Sage company folder.
"""
from __future__ import annotations

import logging
import os
import struct
import threading
import time

import sdk_api
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bridge.sdk")

# ── pythonnet bootstrap ───────────────────────────────────────────────────────
_sdk_loaded = False
_sdk_lock = threading.Lock()

# These are set after load_sdk() succeeds
_peachtree = None   # Sage.Peachtree.API namespace
_session = None     # active PeachtreeSession (singleton, re-used per request)


#: Subdirectories of the Peachtree install probed for dependent assemblies.
#: Mirrors ``<probing privatePath="PBI"/>`` in Peachw.exe.config, plus API
#: itself so the Resolver assembly beside the SDK is found.
_PROBE_SUBDIRS = ("", "API", "PBI")


def _install_dir_for(dll_path: str, install_dir: str = "") -> str:
    """Peachtree program directory: explicit if given, else two levels up from the DLL."""
    if install_dir:
        return os.path.abspath(install_dir)
    return os.path.dirname(os.path.dirname(os.path.abspath(dll_path)))


def _check_bitness(dll_path: str) -> None:
    """
    Refuse to continue under 64-bit Python.

    Sage.Peachtree.API is compiled X86 (verified against the 2013.0.0.826
    build), and the native Pervasive/MFC DLLs it pulls in are 32-bit too. A
    64-bit CLR raises BadImageFormatException on the first real call rather
    than at load, which surfaces as an unrelated-looking failure deep inside a
    sync — so fail here, where the message can say what to do about it.
    """
    if struct.calcsize("P") * 8 != 32:
        raise RuntimeError(
            "The Sage 50 SDK ({}) is a 32-bit (X86) assembly, but this is a "
            "{}-bit Python. Reinstall the bridge under 32-bit Python 3.x and "
            "recreate the virtualenv — there is no 64-bit build of the Sage "
            "2013 SDK.".format(dll_path, struct.calcsize("P") * 8)
        )


def _install_assembly_resolver(install_dir: str) -> None:
    """
    Resolve the SDK's dependent assemblies out of the Peachtree install.

    ``Sage.Peachtree.API.dll`` sits in ``API\\`` but references roughly two
    dozen strong-named siblings — Sage.Peachtree.Common, .DataTypes,
    .BusinessLogic, Sage.SBD.ACS.Framework.*, MFCNet, PRForms, ... — that live
    in the Peachtree root and in ``PBI\\``. Under Peachw.exe the CLR finds them
    because ``Peachw.exe.config`` supplies ``<probing privatePath="PBI"/>`` and
    a binding redirect per assembly onto 2013.0.0.826.

    Nothing of that applies here. The host process is python.exe, so the CLR
    reads *python.exe.config* — which does not exist — and probes only the
    interpreter's own directory. Editing python.exe.config would work but ties
    the bridge to one interpreter and breaks on every Python upgrade.

    An AssemblyResolve handler does the same job from inside the process. It
    fires exactly when the default probe fails, which covers both halves of
    what the config file provided: the wrong directory (handled by searching
    the install dir) and the wrong version (handled implicitly — we match on
    simple name and load whatever 2013.0.0.826 build is on disk, which is the
    redirect target anyway).
    """
    import System  # type: ignore[import]
    from System.Reflection import Assembly  # type: ignore[import]

    search_dirs = [
        os.path.join(install_dir, sub) if sub else install_dir
        for sub in _PROBE_SUBDIRS
    ]
    search_dirs = [d for d in search_dirs if os.path.isdir(d)]

    def _resolve(sender, args):  # noqa: ANN001 — .NET delegate signature
        # args.Name is a full display name: "Sage.Peachtree.Common, Version=..."
        simple_name = args.Name.split(",")[0].strip()
        for directory in search_dirs:
            candidate = os.path.join(directory, simple_name + ".dll")
            if os.path.isfile(candidate):
                try:
                    logger.debug("Resolved %s -> %s", simple_name, candidate)
                    return Assembly.LoadFrom(candidate)
                except Exception as exc:
                    logger.warning("Assembly.LoadFrom failed for %s: %s", candidate, exc)
        logger.warning(
            "Could not resolve Sage dependency '%s' under %s", simple_name, install_dir
        )
        return None

    System.AppDomain.CurrentDomain.AssemblyResolve += System.ResolveEventHandler(_resolve)
    # Held so the delegate is not garbage-collected while the CLR holds it.
    global _resolve_handler
    _resolve_handler = _resolve
    logger.info("Sage assembly resolver probing: %s", ", ".join(search_dirs))


_resolve_handler = None  # keepalive for the AssemblyResolve delegate


#: Types the bridge cannot function without. Checked at load so a mismatched
#: SDK build fails at startup with a precise message instead of an
#: AttributeError several layers into a sync.
_REQUIRED_TYPES = (
    "Sage.Peachtree.API.PeachtreeSession",
    "Sage.Peachtree.API.Company",
    "Sage.Peachtree.API.CompanyIdentifier",
)


def _verify_assembly_usable(dll_path: str) -> None:
    """
    Confirm the loaded assembly's types genuinely resolve.

    Raises RuntimeError with the underlying loader errors if not. See the call
    site for why importing the namespace is not sufficient evidence.
    """
    from System.Reflection import Assembly  # type: ignore[import]

    assembly = Assembly.LoadFrom(dll_path)
    try:
        assembly.GetTypes()
    except Exception as exc:
        # ReflectionTypeLoadException.LoaderExceptions names the exact missing
        # dependency — far more useful than the generic outer message.
        details = []
        for inner in (getattr(exc, "LoaderExceptions", None) or [])[:5]:
            details.append(str(getattr(inner, "Message", inner)))
        raise RuntimeError(
            "Sage.Peachtree.API loaded but its types could not be resolved — a "
            "dependent assembly is missing from the Peachtree install "
            "directory. Underlying errors: {}".format("; ".join(details) or exc)
        ) from exc

    missing = [name for name in _REQUIRED_TYPES if assembly.GetType(name) is None]
    if missing:
        raise RuntimeError(
            "Sage.Peachtree.API loaded but does not expose the expected types: "
            "{}. This is not the Sage 50 2013 SDK the bridge targets "
            "(expected 2013.0.0.826); the API surface differs between "
            "releases.".format(", ".join(missing))
        )


def load_sdk(dll_path: str, install_dir: str = "") -> None:
    """
    Load the Sage.Peachtree.API.dll via pythonnet.
    Call this once at application startup.

    ``install_dir`` is the Peachtree program directory (the folder holding
    Peachw.exe). It is derived from ``dll_path`` when not given.
    """
    global _sdk_loaded, _peachtree

    with _sdk_lock:
        if _sdk_loaded:
            return

        _check_bitness(dll_path)
        resolved_install_dir = _install_dir_for(dll_path, install_dir)
        if not os.path.isdir(resolved_install_dir):
            raise RuntimeError(
                "Peachtree install directory not found: {}. Set SAGE_INSTALL_DIR "
                "to the folder containing Peachw.exe.".format(resolved_install_dir)
            )

        try:
            import pythonnet  # noqa: F401 — version-check import
            pythonnet.load("netfx")  # Must target .NET Framework for Sage SDK
        except Exception as exc:
            logger.error("pythonnet bootstrap failed: %s", exc)
            raise RuntimeError(
                "pythonnet could not load .NET Framework runtime. "
                "Ensure pythonnet is installed (pip install pythonnet) "
                "and the machine has .NET Framework 4.x."
            ) from exc

        try:
            import clr  # noqa: F401
            _install_assembly_resolver(resolved_install_dir)
            clr.AddReference(dll_path)
            import Sage.Peachtree.API as _pt  # type: ignore[import]

            # Verify the assembly's types actually resolve before declaring
            # success. `import Sage.Peachtree.API` goes through pythonnet's CLR
            # import hook, which returns a lazily-populated namespace object —
            # it succeeds even when the assembly's dependencies are missing and
            # not one type can be constructed. Reporting "loaded" on the
            # strength of that import alone pushes the real failure out to the
            # first SDK call, where it surfaces as an unrelated-looking error
            # in the middle of a sync.
            #
            # Assembly.GetTypes() is the honest check: it throws
            # ReflectionTypeLoadException if any dependency failed to resolve.
            _verify_assembly_usable(dll_path)

            _peachtree = _pt
            _sdk_loaded = True
            logger.info(
                "Sage.Peachtree.API loaded and verified from: %s (install dir: %s)",
                dll_path, resolved_install_dir,
            )
        except Exception as exc:
            logger.error("Failed to load Sage SDK DLL from %s: %s", dll_path, exc)
            raise RuntimeError(
                f"Could not load Sage.Peachtree.API.dll from '{dll_path}'. "
                "Ensure Sage 50 2013 is installed and the DLL path is correct."
            ) from exc


def _authorization_help(result) -> str:
    """
    Turn an AuthorizationResult into an instruction the operator can act on.

    The enum values are the SDK's own vocabulary and each means something
    genuinely different; collapsing them into "SDK unavailable" is what makes
    this failure take an afternoon instead of five minutes.
    """
    name = str(result)
    guidance = {
        "Pending": (
            "Sage is waiting for a human to approve this application. Open "
            "Sage 50 on this machine as an admin user, go to the third-party "
            "access prompt and click Allow, then restart the bridge. A Windows "
            "service cannot answer that dialog — see INSTALL.md 3.4."
        ),
        "Denied": (
            "Access was explicitly DENIED. In Sage 50: Maintain > Users > "
            "Third-party access, remove the denial for this application, then "
            "restart the bridge."
        ),
        "CompanyLocked": (
            "The company is locked — usually a single-user Sage session has it "
            "open exclusively, or a backup/restore is running. Close Sage or "
            "wait for the operation to finish."
        ),
        "LoginRestricted": (
            "The Sage user account is restricted from third-party access. Grant "
            "it API rights in Sage 50 under Maintain > Users."
        ),
        "NoCredentials": (
            "The company requires a Sage login and none was supplied. This "
            "company has user security enabled; the bridge does not currently "
            "pass credentials — see KNOWN_LIMITATIONS.md."
        ),
        "CorruptedOrTampered": (
            "Sage reports the authorization record is corrupted or tampered "
            "with. Revoke and re-grant third-party access in Sage 50."
        ),
        "None": (
            "No authorization record exists yet. Open Sage 50 and approve the "
            "access prompt for this application."
        ),
    }.get(name, "Unrecognised authorization state.")

    return "Sage SDK authorization is '{}'. {}".format(name, guidance)


# ── Session management ────────────────────────────────────────────────────────

class SageSession:
    """
    Wrapper around a PeachtreeSession + open Company, with health checking and
    automatic reconnection.

    Two problems with the original are fixed here.

    **1. A dead session never recovered.** ``_ensure_open`` reopened only when
    ``_session is None``. If Sage was closed and reopened, the company file got
    locked, or the session died for any other reason, the object was non-None
    but unusable — every subsequent call failed until someone restarted the
    service. ``_is_healthy()`` now probes the session and reconnects when the
    probe fails.

    **2. Concurrent SDK access.** The lock guarded only the *opening* of the
    session; the ``sdk_get_*`` functions then hit the .NET objects from
    whichever FastAPI threadpool worker they landed on. The Peachtree API is
    not documented thread-safe, and COM/.NET interop under pythonnet is
    apartment-sensitive. ``access()`` now serialises every SDK call through one
    reentrant lock.

    Serialising costs throughput, but this bridge handles a handful of
    invoices a minute on a single-user Sage install — correctness is worth far
    more than parallelism here.
    """

    #: Reconnect attempts before giving up on a single call.
    _MAX_RECONNECT = 2

    def __init__(self, company_path: str, application_id: str = "") -> None:
        self._company_path = company_path
        self._application_id = application_id or "PlacewareSynBotBridge"
        self._session = None
        self._company = None
        self._company_identifier = None
        self._authorization = ""
        # Reentrant: access() may be nested by helpers that also take it.
        self._lock = threading.RLock()
        self._consecutive_failures = 0

    # ── connection state ─────────────────────────────────────────────────────

    def _resolve_company_identifier(self, session):
        """
        Find the CompanyIdentifier matching the configured company path.

        ``PeachtreeSession.Open`` takes a CompanyIdentifier, NOT a path string —
        the old code passed the path directly, which cannot bind. The identifier
        must be obtained from the session, which enumerates the companies Sage
        knows about.

        Matching is on ``Path`` (case-insensitive, trailing separators ignored,
        since operators write the path with or without a trailing backslash),
        falling back to ``CompanyName`` so a configured name also works.
        """
        wanted = os.path.normcase(os.path.normpath(self._company_path.strip()))

        try:
            candidates = list(session.CompanyList())
        except Exception as exc:
            raise RuntimeError(
                "Could not enumerate Sage companies: {}. The Pervasive engine "
                "may not be running, or this user cannot see the company "
                "folder.".format(exc)
            ) from exc

        if not candidates:
            raise RuntimeError(
                "Sage reports no companies. Confirm Sage 50 has opened this "
                "company at least once on this machine, and that the Pervasive "
                "Workgroup Engine service is running."
            )

        available = []
        for cid in candidates:
            cid_path = sdk_api.text(getattr(cid, "Path", ""))
            cid_name = sdk_api.text(getattr(cid, "CompanyName", ""))
            available.append("{} ({})".format(cid_name, cid_path))
            if cid_path and os.path.normcase(os.path.normpath(cid_path)) == wanted:
                return cid
            if cid_name and cid_name.lower() == self._company_path.strip().lower():
                return cid

        raise RuntimeError(
            "No Sage company matches SAGE_COMPANY_PATH={!r}. Sage knows about: "
            "{}".format(self._company_path, "; ".join(available))
        )

    def _authorize(self, session, company_identifier) -> None:
        """
        Ensure this application is authorized against the company.

        The SDK gates access behind a one-time consent the user grants inside
        Sage. ``VerifyAccess`` asks whether we already have it; ``RequestAccess``
        raises the prompt. A service cannot answer that prompt, so the useful
        thing here is to report the *specific* state rather than a generic
        failure — the difference between "someone must click Allow in Sage",
        "the company is locked by another process", and "access was denied" is
        the difference between a five-minute fix and an afternoon.
        """
        try:
            result = session.VerifyAccess(company_identifier)
        except Exception as exc:
            logger.warning("VerifyAccess failed (%s) — trying RequestAccess.", exc)
            result = None

        granted = _peachtree.AuthorizationResult.Granted

        if result != granted:
            try:
                result = session.RequestAccess(company_identifier)
            except Exception as exc:
                raise RuntimeError(
                    "Sage SDK access request failed: {}".format(exc)
                ) from exc

        self._authorization = str(result)

        if result == granted:
            return

        raise RuntimeError(_authorization_help(result))

    def _open(self) -> None:
        """Open a Sage session and the company. Caller holds the lock."""
        if not _sdk_loaded:
            raise RuntimeError("SDK not loaded. Call load_sdk() first.")

        session = _peachtree.PeachtreeSession()
        # Begin takes an application identifier string. There is no ProductType
        # type in this assembly — the old ProductType.Peachtree call could never
        # have run.
        session.Begin(self._application_id)

        try:
            company_identifier = self._resolve_company_identifier(session)
            self._authorize(session, company_identifier)
            company = session.Open(company_identifier)
        except Exception:
            # Do not leak the session if anything after Begin() fails.
            try:
                session.End()
            except Exception:
                pass
            raise

        self._session = session
        self._company = company
        self._company_identifier = company_identifier
        self._consecutive_failures = 0
        # Reference IDs are cached per company; a reopen may be a different one.
        sdk_api.clear_reference_cache()
        logger.info(
            "Sage company opened: %s (%s)",
            sdk_api.text(getattr(company_identifier, "CompanyName", "?")),
            self._company_path,
        )

    def _is_healthy(self) -> bool:
        """
        Probe whether the session is still usable.

        ``Company`` has no ``Name`` property — the old probe touched one that
        does not exist, so it raised every time and the session was judged dead
        on every single check. The real signals are ``Company.IsClosed`` and
        ``PeachtreeSession.SessionActive``.
        """
        if self._session is None or self._company is None:
            return False
        try:
            if self._company.IsClosed:
                logger.warning("Sage company reports IsClosed.")
                return False
            if not self._session.SessionActive:
                logger.warning("Sage session reports SessionActive=False.")
                return False
            return True
        except Exception as exc:
            logger.warning("Sage session failed health probe: %s", exc)
            return False

    def _reconnect(self) -> None:
        """Tear down and reopen. Caller holds the lock."""
        logger.info("Reopening Sage session...")
        self._close_locked()
        self._open()

    def _ensure_open(self) -> None:
        with self._lock:
            if not self._is_healthy():
                self._reconnect()

    # ── serialised access ────────────────────────────────────────────────────

    @contextmanager
    def access(self):
        """
        Context manager yielding the live Company object under an exclusive lock.

        Every SDK call must go through this::

            with _get_session().access() as company:
                company.Factories...

        Reconnects transparently if the session has died, retrying the caller's
        work is NOT attempted — the caller sees the exception and the sync layer
        leaves the event pending, so nothing is lost.
        """
        with self._lock:
            attempt = 0
            while True:
                if self._is_healthy():
                    break
                attempt += 1
                if attempt > self._MAX_RECONNECT:
                    self._consecutive_failures += 1
                    raise RuntimeError(
                        "Sage SDK session unavailable after {} reconnect "
                        "attempts (consecutive failures: {}). Check that Sage 50 "
                        "is installed, the company path is correct, and the SDK "
                        "authorization has been granted — see INSTALL.md."
                        .format(self._MAX_RECONNECT, self._consecutive_failures)
                    )
                try:
                    self._reconnect()
                except Exception as exc:
                    logger.error("Sage reconnect attempt %d failed: %s", attempt, exc)
                    time.sleep(1.0 * attempt)
            yield self._company

    @property
    def company(self):
        """Backwards-compatible accessor. Prefer access() for new code."""
        self._ensure_open()
        return self._company

    def health(self) -> Dict[str, Any]:
        """Report session state for /health and /sync/status."""
        with self._lock:
            healthy = self._is_healthy()
            company_name = ""
            if self._company_identifier is not None:
                company_name = sdk_api.text(
                    getattr(self._company_identifier, "CompanyName", "")
                )
        return {
            "sdk_loaded": _sdk_loaded,
            "session_open": self._session is not None,
            "healthy": healthy,
            "company_path": self._company_path,
            "company_name": company_name,
            # Surfaced because "not authorized yet" is the single most common
            # first-install failure and is otherwise indistinguishable from a
            # dead session.
            "authorization": self._authorization,
            "consecutive_failures": self._consecutive_failures,
        }

    # ── teardown ─────────────────────────────────────────────────────────────

    def _close_locked(self) -> None:
        # Order matters: the session owns the company. Closing via the session
        # is the documented path; Company.Close() exists but leaves the session
        # holding a reference.
        if self._session is not None and self._company is not None:
            try:
                self._session.Close(self._company)
            except Exception:
                pass
        if self._session is not None:
            try:
                self._session.End()
            except Exception:
                pass
            try:
                self._session.Dispose()
            except Exception:
                pass
        self._session = None
        self._company = None
        self._company_identifier = None
        sdk_api.clear_reference_cache()

    def close(self) -> None:
        with self._lock:
            self._close_locked()
            logger.info("Sage session closed.")


# Module-level singleton session (initialised in main.py startup)
_sage_session: Optional[SageSession] = None


def init_session(company_path: str, application_id: str = "") -> None:
    """Initialise the module-level SageSession. Call once at startup."""
    global _sage_session
    _sage_session = SageSession(company_path, application_id)
    _sage_session._ensure_open()


def _get_session() -> SageSession:
    if _sage_session is None:
        raise RuntimeError("SageSession not initialised. Call init_session() first.")
    return _sage_session


def sdk_health() -> Dict[str, Any]:
    """
    Report SDK availability without raising. Used by /health and /sync/status.

    Returns a dict rather than a bool so operators can tell "Sage not installed"
    apart from "session died" apart from "not authorized yet" — three very
    different problems that all previously surfaced as sdk_connected: false.
    """
    if _is_mock():
        return {"sdk_loaded": True, "session_open": True, "healthy": True,
                "mode": "mock"}
    if _sage_session is None:
        return {
            "sdk_loaded": _sdk_loaded,
            "session_open": False,
            "healthy": False,
            "reason": "session not initialised (SDK load or company open failed "
                      "at startup — check the log for the underlying error)",
        }
    return _sage_session.health()


def _is_mock() -> bool:
    """True when running in mock mode — no Sage DLL or company file required."""
    try:
        from config import get_settings
        return get_settings().SAGE_MOCK
    except Exception:
        return False


# ── Shared helpers ───────────────────────────────────────────────────────────
#
# Every read below follows the same shape, because the real API only offers one:
#
#     with _get_session().access() as company:
#         items = sdk_api.load_list(company.Factories.<X>Factory.List(), limit)
#
# `List()` returns an EMPTY EntityList until `.Load()` is called — see
# sdk_api.load_list. Forgetting that yields zero rows and looks exactly like a
# company with no data, which is why it is centralised there rather than
# repeated at each call site.

def _net_date(d: date) -> Any:
    """System.DateTime from a Python date."""
    return sdk_api.net_datetime(d)


def _py_date(value) -> Optional[str]:
    """CLR DateTime (or Nullable) to ISO string, or None."""
    return sdk_api.iso_date(value)


def _safe(val: Any, default: Any = None) -> Any:
    try:
        return val if val is not None else default
    except Exception:
        return default


def _factory(company, name: str):
    """
    Fetch a factory off Company.Factories, with a clear error if absent.

    Factory names differ from the entity names the old code assumed (there is
    no `SalesInvoices` collection; there is a `SalesInvoiceFactory`), so a typo
    here should say so rather than surface as a bare AttributeError.
    """
    factories = company.Factories
    factory = getattr(factories, name, None)
    if factory is None:
        raise RuntimeError(
            "Sage.Peachtree.API exposes no {} on Company.Factories. This build "
            "of the SDK differs from 2013.0.0.826.".format(name)
        )
    return factory


def _entity_guid(entity) -> str:
    """
    Stable string ID for an entity whose real key is a Guid.

    Transactions have no human-readable primary key in the SDK — `Key` is an
    EntityReference carrying a Guid. ReferenceNumber is the *user-visible*
    number and is not guaranteed unique, so the Guid is what we key on.
    """
    try:
        return str(entity.Key.Guid)
    except Exception:
        return ""


def _iter_limited(items, limit: int):
    for idx, item in enumerate(items):
        if idx >= limit:
            return
        yield item


# ── CUSTOMERS ─────────────────────────────────────────────────────────────────

def sdk_get_customers(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_CUSTOMERS, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "CustomerFactory").List(), limit)
        return [_customer_to_dict(c, company) for c in items]


def sdk_get_customer(customer_id: str) -> Optional[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return next((c for c in md.MOCK_CUSTOMERS if c["id"] == customer_id), None)
    with _get_session().access() as company:
        for c in sdk_api.load_list(_factory(company, "CustomerFactory").List()):
            if sdk_api.text(c.ID) == customer_id.strip():
                return _customer_to_dict(c, company)
    return None


def sdk_create_customer(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a customer in Sage and return the created record."""
    if _is_mock():
        import mock_data as md
        record = {"is_active": True, **data}
        md.MOCK_CUSTOMERS.append(record)
        logger.info("[MOCK] Customer created: %s", data.get("id"))
        return record

    with _get_session().access() as company:
        customer = _factory(company, "CustomerFactory").Create()
        customer.ID = data["id"]
        customer.Name = data["name"]
        customer.Email = _safe(data.get("email"), "")

        # Address and phone live on the BillToContact, not on the customer.
        _apply_contact(customer.BillToContact, data)

        if data.get("credit_limit") is not None:
            # CreditLimit is on PaymentTerms, which is a struct-like value —
            # mutate a copy and assign it back, or the change is discarded.
            terms = customer.Terms
            terms.CreditLimit = _decimal(data["credit_limit"])
            customer.Terms = terms

        _save_entity(customer, "customer {}".format(data.get("id")))
        logger.info("Customer created in Sage: %s", sdk_api.text(customer.ID))
        return _customer_to_dict(customer, company)


def sdk_update_customer(customer_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing customer. Only fields present in ``data`` change."""
    if _is_mock():
        import mock_data as md
        for c in md.MOCK_CUSTOMERS:
            if c["id"] == customer_id:
                c.update(data)
                return c
        raise ValueError("Customer '{}' not found".format(customer_id))

    with _get_session().access() as company:
        customer = None
        for c in sdk_api.load_list(_factory(company, "CustomerFactory").List()):
            if sdk_api.text(c.ID) == customer_id.strip():
                customer = c
                break
        if customer is None:
            raise ValueError("Customer '{}' not found in Sage".format(customer_id))

        if "name" in data:
            customer.Name = data["name"]
        if "email" in data:
            customer.Email = data["email"]
        _apply_contact(customer.BillToContact, data, partial=True)
        if "credit_limit" in data:
            terms = customer.Terms
            terms.CreditLimit = _decimal(data["credit_limit"])
            customer.Terms = terms

        _save_entity(customer, "customer {}".format(customer_id))
        logger.info("Customer updated in Sage: %s", customer_id)
        return _customer_to_dict(customer, company)


def _apply_contact(contact, data: Dict[str, Any], partial: bool = False) -> None:
    """
    Write address/phone/contact fields onto a Contact.

    ``partial`` skips keys the caller did not supply, so an update does not
    blank out fields it never mentioned.
    """
    if contact is None:
        return

    def want(key: str) -> bool:
        return key in data if partial else True

    address = contact.Address
    if address is not None:
        if want("address1"):
            address.Address1 = _safe(data.get("address1"), "")
        if want("address2"):
            address.Address2 = _safe(data.get("address2"), "")
        if want("city"):
            address.City = _safe(data.get("city"), "")
        if want("state"):
            address.State = _safe(data.get("state"), "")
        if want("zip"):
            address.Zip = _safe(data.get("zip"), "")
        if want("country"):
            address.Country = _safe(data.get("country"), "")

    if want("contact") and data.get("contact"):
        contact.Name = data["contact"]
    if want("email") and data.get("email"):
        contact.Email = data["email"]


def _customer_to_dict(c, company) -> Dict[str, Any]:
    """
    Map a Sage Customer to the wire format.

    Field sources differ substantially from what the old code assumed:
      Balance          not CurrentBalance
      BillToContact    holds the address; there is no BillingAddress property
      PhoneNumbers[n]  indexed collection; no Telephone1 / Fax properties
      Terms.CreditLimit  credit limit lives on PaymentTerms
      not IsInactive   there is no IsActive
    """
    contact = getattr(c, "BillToContact", None)
    addr = sdk_api.contact_address(contact)
    terms = getattr(c, "Terms", None)

    return {
        "id": sdk_api.text(c.ID),
        "name": sdk_api.text(c.Name),
        "address1": addr["address1"],
        "address2": addr["address2"],
        "city": addr["city"],
        "state": addr["state"],
        "zip": addr["zip"],
        "country": addr["country"],
        "phone": sdk_api.phone_at(getattr(c, "PhoneNumbers", None), 0),
        "fax": sdk_api.phone_at(getattr(c, "PhoneNumbers", None), 2),
        "email": sdk_api.text(c.Email),
        "contact": sdk_api.text(getattr(contact, "Name", "")),
        "balance": sdk_api.num(getattr(c, "Balance", 0)),
        "credit_limit": sdk_api.num(getattr(terms, "CreditLimit", 0)),
        "is_active": not bool(getattr(c, "IsInactive", False)),
        "account_number": sdk_api.text(getattr(c, "AccountNumber", "")),
        "category": sdk_api.text(getattr(c, "Category", "")),
        "last_invoice_date": _py_date(getattr(c, "LastInvoiceDate", None)),
        "last_payment_date": _py_date(getattr(c, "LastPaymentDate", None)),
    }


# ── VENDORS ───────────────────────────────────────────────────────────────────

def sdk_get_vendors(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_VENDORS, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "VendorFactory").List(), limit)
        return [_vendor_to_dict(v) for v in items]


def sdk_get_vendor(vendor_id: str) -> Optional[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return next((v for v in md.MOCK_VENDORS if v["id"] == vendor_id), None)
    with _get_session().access() as company:
        for v in sdk_api.load_list(_factory(company, "VendorFactory").List()):
            if sdk_api.text(v.ID) == vendor_id.strip():
                return _vendor_to_dict(v)
    return None


def sdk_create_vendor(data: Dict[str, Any]) -> Dict[str, Any]:
    if _is_mock():
        import mock_data as md
        record = {"is_active": True, "balance": 0.0, **data}
        md.MOCK_VENDORS.append(record)
        logger.info("[MOCK] Vendor created: %s", data.get("id"))
        return record

    with _get_session().access() as company:
        vendor = _factory(company, "VendorFactory").Create()
        vendor.ID = data["id"]
        vendor.Name = data["name"]
        vendor.Email = _safe(data.get("email"), "")
        # Vendor's address contact is MailToContact, not PurchasesAddress.
        _apply_contact(vendor.MailToContact, data)
        _save_entity(vendor, "vendor {}".format(data.get("id")))
        logger.info("Vendor created in Sage: %s", sdk_api.text(vendor.ID))
        return _vendor_to_dict(vendor)


def _vendor_to_dict(v) -> Dict[str, Any]:
    contact = getattr(v, "MailToContact", None)
    addr = sdk_api.contact_address(contact)
    return {
        "id": sdk_api.text(v.ID),
        "name": sdk_api.text(v.Name),
        "address1": addr["address1"],
        "address2": addr["address2"],
        "city": addr["city"],
        "state": addr["state"],
        "zip": addr["zip"],
        "country": addr["country"],
        "phone": sdk_api.phone_at(getattr(v, "PhoneNumbers", None), 0),
        "email": sdk_api.text(v.Email),
        "contact": sdk_api.text(getattr(contact, "Name", "")),
        "balance": sdk_api.num(getattr(v, "Balance", 0)),
        "tax_id": sdk_api.text(getattr(v, "TaxIDNumber", "")),
        "is_active": not bool(getattr(v, "IsInactive", False)),
    }


# ── SALES INVOICES ────────────────────────────────────────────────────────────

def sdk_get_invoices(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    customer_id: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        data = md.MOCK_INVOICES
        if customer_id:
            data = [i for i in data if i.get("customer_id") == customer_id]
        if from_date:
            data = [i for i in data if i.get("date", "") >= str(from_date)]
        if to_date:
            data = [i for i in data if i.get("date", "") <= str(to_date)]
        return md.paginate(data, limit, 0)

    with _get_session().access() as company:
        result: List[Dict[str, Any]] = []
        for inv in sdk_api.load_list(_factory(company, "SalesInvoiceFactory").List()):
            if len(result) >= limit:
                break
            inv_date = _py_date(inv.Date)
            if from_date and inv_date and inv_date < str(from_date):
                continue
            if to_date and inv_date and inv_date > str(to_date):
                continue
            record = _invoice_to_dict(inv, company)
            if customer_id and record["customer_id"] != customer_id.strip():
                continue
            result.append(record)
        return result


# ── bulk-read window ─────────────────────────────────────────────────────────
#
# The SDK offers no "get invoice by id" — EntityFactory.Load() takes an
# EntityReference (a Guid we do not have when coming from an ODBC scan), so a
# lookup means enumerating the invoice list.
#
# That makes the scan path quadratic. The watcher scans a page of invoices and
# calls extract_invoice() per invoice, each of which calls sdk_get_invoice(),
# each of which does a full factory List() + Load() of EVERY invoice in the
# company. One page of 100 invoices against a company with 20 000 of them is
# 2 000 000 row visits and 100 full table loads — per tick. On the target
# hardware that does not merely run slowly, it never finishes a scan.
#
# The fix is an explicit window rather than a time-based cache: the watcher says
# "I am about to read a batch", the first lookup loads the list once, every
# lookup in that batch reuses it, and the window closes at the end of the scan.
# Explicit beginning and end mean no staleness policy to reason about — the
# snapshot cannot outlive the scan that asked for it.

_bulk_lock = threading.RLock()
_bulk_depth = 0
_bulk_invoice_index: Optional[Dict[str, Any]] = None


@contextmanager
def bulk_read():
    """
    Reuse one loaded invoice snapshot for every lookup inside this block.

    Re-entrant, so nested use is safe. Always release via the context manager;
    the snapshot is dropped on exit so the next scan sees fresh data.

        with sdk.bulk_read():
            for sage_id in page:
                invoice_extract.extract_invoice(sage_id)
    """
    global _bulk_depth, _bulk_invoice_index
    with _bulk_lock:
        _bulk_depth += 1
    try:
        yield
    finally:
        with _bulk_lock:
            _bulk_depth -= 1
            if _bulk_depth <= 0:
                _bulk_depth = 0
                _bulk_invoice_index = None


def _invoice_index(company) -> Dict[str, Any]:
    """
    Map {guid or reference number -> SalesInvoice}, built at most once per
    bulk_read() window. Outside a window it is rebuilt per call.
    """
    global _bulk_invoice_index
    with _bulk_lock:
        if _bulk_depth > 0 and _bulk_invoice_index is not None:
            return _bulk_invoice_index

    index: Dict[str, Any] = {}
    for inv in sdk_api.load_list(_factory(company, "SalesInvoiceFactory").List()):
        guid = _entity_guid(inv)
        if guid:
            index[guid] = inv
        ref = sdk_api.text(getattr(inv, "ReferenceNumber", ""))
        # Reference numbers are not guaranteed unique; first wins, and the Guid
        # entry above is always the unambiguous way in.
        if ref and ref not in index:
            index[ref] = inv

    with _bulk_lock:
        if _bulk_depth > 0:
            _bulk_invoice_index = index
            logger.debug("Bulk-read invoice index built: %d key(s)", len(index))
    return index


def sdk_get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch one invoice by identifier.

    ``invoice_id`` may be either the SDK Guid or the user-visible
    ReferenceNumber. Both are accepted because the two halves of this bridge
    identify invoices differently: the ODBC scan keys on ARTRANS.TRANSNO (which
    maps to the reference number), while the SDK's own primary key is a Guid.
    Matching on both keeps the SDK and ODBC paths interchangeable.

    Wrap batches in ``bulk_read()`` — see the note above on why a naive loop
    over this function is quadratic.
    """
    if _is_mock():
        import mock_data as md
        return next((i for i in md.MOCK_INVOICES if i["sage_id"] == invoice_id), None)

    wanted = invoice_id.strip()
    with _get_session().access() as company:
        inv = _invoice_index(company).get(wanted)
        return _invoice_to_dict(inv, company) if inv is not None else None


def sdk_create_invoice(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a Sales Invoice in Sage, which triggers Sage's own ledger posting.

    ``data`` matches the shape documented on the HTTP route: customer_id, date,
    due_date, lines[{description, quantity, unit_price, gl_account, item_id}],
    plus optional invoice_number, po_number, note, ship_method.
    """
    if _is_mock():
        import mock_data as md, uuid as _uuid
        sage_id = "INV-MOCK-{}".format(_uuid.uuid4().hex[:6].upper())
        record = {
            "sage_id": sage_id,
            "customer_id": data["customer_id"],
            "date": data["date"],
            "due_date": data["due_date"],
            "invoice_number": data.get("invoice_number", sage_id),
            "po_number": data.get("po_number", ""),
            "total_amount": sum(
                float(l.get("quantity", 1)) * float(l.get("unit_price", 0))
                for l in data.get("lines", [])
            ),
            "amount_paid": 0.0, "amount_due": 0.0, "is_paid": False,
            "note": data.get("note", ""), "lines": data.get("lines", []),
        }
        md.MOCK_INVOICES.append(record)
        logger.info("[MOCK] Invoice created: %s", sage_id)
        return record

    with _get_session().access() as company:
        invoice = _factory(company, "SalesInvoiceFactory").Create()

        customer = _find_entity(company, "CustomerFactory", data["customer_id"])
        if customer is None:
            raise ValueError(
                "Customer '{}' not found in Sage — cannot create the invoice."
                .format(data["customer_id"])
            )
        # References are assigned from the target entity's Key, not from an ID
        # string. The old code assigned the string directly, which cannot bind.
        invoice.CustomerReference = customer.Key

        invoice.Date = _net_date(date.fromisoformat(data["date"]))
        if data.get("due_date"):
            invoice.DateDue = _net_date(date.fromisoformat(data["due_date"]))
        if data.get("invoice_number"):
            invoice.ReferenceNumber = data["invoice_number"]
        if data.get("po_number"):
            invoice.CustomerPurchaseOrderNumber = data["po_number"]
        if data.get("note"):
            invoice.CustomerNote = data["note"]
        if data.get("ship_method"):
            invoice.ShipVia = data["ship_method"]

        for line_data in data.get("lines", []):
            line = invoice.AddSalesLine()
            line.Description = _safe(line_data.get("description"), "")
            line.Quantity = _decimal(line_data.get("quantity", 1))
            line.UnitPrice = _decimal(line_data.get("unit_price", 0))
            if line_data.get("gl_account"):
                account = _find_entity(company, "AccountFactory", line_data["gl_account"])
                if account is not None:
                    line.AccountReference = account.Key
            if line_data.get("item_id"):
                item = _find_inventory_item(company, line_data["item_id"])
                if item is not None:
                    line.InventoryItemReference = item.Key

        _save_entity(invoice, "sales invoice for {}".format(data["customer_id"]))
        sage_id = _entity_guid(invoice)
        logger.info(
            "Sales invoice created in Sage: %s (customer: %s)",
            sage_id, data["customer_id"],
        )
        return _invoice_to_dict(invoice, company)


def sdk_void_invoice(invoice_id: str) -> bool:
    """Delete a sales invoice by Guid or reference number."""
    if _is_mock():
        import mock_data as md
        before = len(md.MOCK_INVOICES)
        md.MOCK_INVOICES[:] = [i for i in md.MOCK_INVOICES if i["sage_id"] != invoice_id]
        logger.info("[MOCK] Invoice voided: %s", invoice_id)
        return len(md.MOCK_INVOICES) < before

    wanted = invoice_id.strip()
    with _get_session().access() as company:
        for inv in sdk_api.load_list(_factory(company, "SalesInvoiceFactory").List()):
            if _entity_guid(inv) != wanted and sdk_api.text(inv.ReferenceNumber) != wanted:
                continue
            if not bool(getattr(inv, "IsDeleteAllowed", True)):
                raise RuntimeError(
                    "Sage refuses deletion of invoice {} (IsDeleteAllowed is "
                    "false) — it is probably posted to a closed period."
                    .format(invoice_id)
                )
            inv.Delete()
            logger.info("Sage invoice voided: %s", invoice_id)
            return True
    return False


def _invoice_to_dict(inv, company) -> Dict[str, Any]:
    """
    Map a Sage SalesInvoice to the wire format.

    Field sources, all verified against the assembly — the old names in
    brackets do not exist:

        Amount                       [TotalAmount]
        AmountDue                    [AmountDue was right]
        Amount - AmountDue           [AmountPaid] — derived, no such property
        DateDue                      [DueDate]
        ReferenceNumber              [ReferenceNumber was right]
        CustomerPurchaseOrderNumber  [CustomerPurchaseOrderNumber was right]
        CustomerNote                 [Note]
        ApplyToSalesLines            [SalesInvoiceLines]
        SalesTaxAmount               [SalesTaxAmount was right]

    There is no ShipDate on SalesInvoice (SalesOrder has one), and no per-line
    tax amount — SalesTaxType is an integer code, not money.
    """
    total = sdk_api.num(inv.Amount)
    due = sdk_api.num(inv.AmountDue)

    customer = sdk_api.resolve_reference(company, getattr(inv, "CustomerReference", None))

    lines: List[Dict[str, Any]] = []
    try:
        collection = inv.ApplyToSalesLines
        for idx in range(collection.Count):
            line = collection[idx]
            lines.append({
                "line_no": idx + 1,
                "description": sdk_api.text(getattr(line, "Description", "")),
                "quantity": sdk_api.num(getattr(line, "Quantity", 0)),
                "unit_price": sdk_api.num(getattr(line, "UnitPrice", 0)),
                "amount": round(sdk_api.num(getattr(line, "Amount", 0)), 2),
                "gl_account": sdk_api.reference_id(
                    company, getattr(line, "AccountReference", None)),
                "item_id": sdk_api.reference_id(
                    company, getattr(line, "InventoryItemReference", None)),
                # An integer tax CODE, not an amount. Sage computes tax at the
                # invoice level; there is no per-line tax money in this API.
                "tax_type": str(getattr(line, "SalesTaxType", "") or ""),
                "tax_amount": 0.0,
            })
    except Exception as exc:
        # Not swallowed: a header with no lines looks like a valid empty invoice
        # downstream and would zero out the inventory movement for a real sale.
        logger.error(
            "Failed reading invoice lines for %s: %s — record marked incomplete",
            _entity_guid(inv), exc,
        )
        raise

    return {
        "sage_id": _entity_guid(inv),
        "customer_id": customer["id"],
        "customer_name": customer["name"],
        "date": _py_date(inv.Date),
        "due_date": _py_date(getattr(inv, "DateDue", None)),
        # SalesInvoice has no ship date; only SalesOrder does.
        "ship_date": None,
        "ship_method": sdk_api.text(getattr(inv, "ShipVia", "")),
        "invoice_number": sdk_api.text(getattr(inv, "ReferenceNumber", "")),
        "po_number": sdk_api.text(getattr(inv, "CustomerPurchaseOrderNumber", "")),
        "total_amount": total,
        "amount_paid": round(total - due, 2),
        "amount_due": due,
        "sales_tax_amount": sdk_api.num(getattr(inv, "SalesTaxAmount", 0)),
        "tax_code": sdk_api.reference_id(
            company, getattr(inv, "SalesTaxCodeReference", None)),
        "freight_amount": sdk_api.num(getattr(inv, "FreightAmount", 0)),
        "discount_amount": sdk_api.num(getattr(inv, "DiscountAmount", 0)),
        "is_paid": due <= 0.005,
        "is_posted": bool(getattr(inv, "IsPosted", False)),
        "note": sdk_api.text(getattr(inv, "CustomerNote", "")),
        "internal_note": sdk_api.text(getattr(inv, "InternalNote", "")),
        "terms": sdk_api.text(getattr(inv, "TermsDescription", "")),
        "lines": lines,
    }


# ── SALES ORDERS ──────────────────────────────────────────────────────────────

def sdk_get_sales_orders(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_SALES_ORDERS, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "SalesOrderFactory").List(), limit)
        return [_sales_order_to_dict(so, company) for so in items]


def sdk_create_sales_order(data: Dict[str, Any]) -> Dict[str, Any]:
    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": "SO-MOCK-{}".format(_uuid.uuid4().hex[:6].upper()), **data}
        md.MOCK_SALES_ORDERS.append(record)
        logger.info("[MOCK] Sales order created")
        return record

    with _get_session().access() as company:
        so = _factory(company, "SalesOrderFactory").Create()
        customer = _find_entity(company, "CustomerFactory", data["customer_id"])
        if customer is None:
            raise ValueError("Customer '{}' not found".format(data["customer_id"]))
        so.CustomerReference = customer.Key
        so.Date = _net_date(date.fromisoformat(data["date"]))
        if data.get("ship_date"):
            so.ShipByDate = _net_date(date.fromisoformat(data["ship_date"]))
        if data.get("po_number"):
            so.CustomerPurchaseOrderNumber = data["po_number"]
        if data.get("reference"):
            so.ReferenceNumber = data["reference"]

        for line_data in data.get("lines", []):
            line = so.AddLine()
            line.Description = _safe(line_data.get("description"), "")
            line.Quantity = _decimal(line_data.get("quantity", 1))
            line.UnitPrice = _decimal(line_data.get("unit_price", 0))
            if line_data.get("item_id"):
                item = _find_inventory_item(company, line_data["item_id"])
                if item is not None:
                    line.InventoryItemReference = item.Key

        _save_entity(so, "sales order")
        logger.info("Sales order created in Sage: %s", _entity_guid(so))
        return _sales_order_to_dict(so, company)


def _sales_order_to_dict(so, company) -> Dict[str, Any]:
    lines = []
    try:
        collection = so.SalesOrderLines
        for idx in range(collection.Count):
            line = collection[idx]
            lines.append({
                "line_no": idx + 1,
                "description": sdk_api.text(getattr(line, "Description", "")),
                "quantity": sdk_api.num(getattr(line, "Quantity", 0)),
                "unit_price": sdk_api.num(getattr(line, "UnitPrice", 0)),
                "item_id": sdk_api.reference_id(
                    company, getattr(line, "InventoryItemReference", None)),
            })
    except Exception as exc:
        logger.warning("Could not read sales order lines for %s: %s",
                       _entity_guid(so), exc)
    return {
        "sage_id": _entity_guid(so),
        "customer_id": sdk_api.reference_id(
            company, getattr(so, "CustomerReference", None)),
        "date": _py_date(so.Date),
        "ship_date": _py_date(getattr(so, "ShipByDate", None)),
        "po_number": sdk_api.text(getattr(so, "CustomerPurchaseOrderNumber", "")),
        "reference": sdk_api.text(getattr(so, "ReferenceNumber", "")),
        "total_amount": sdk_api.num(so.Amount),
        "is_closed": bool(getattr(so, "IsClosed", False)),
        "lines": lines,
    }


# ── PURCHASE ORDERS ───────────────────────────────────────────────────────────

def sdk_get_purchase_orders(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_PURCHASE_ORDERS, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "PurchaseOrderFactory").List(), limit)
        return [_purchase_order_to_dict(po, company) for po in items]


def sdk_create_purchase_order(data: Dict[str, Any]) -> Dict[str, Any]:
    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": "PO-MOCK-{}".format(_uuid.uuid4().hex[:6].upper()), **data}
        md.MOCK_PURCHASE_ORDERS.append(record)
        logger.info("[MOCK] Purchase order created")
        return record

    with _get_session().access() as company:
        po = _factory(company, "PurchaseOrderFactory").Create()
        vendor = _find_entity(company, "VendorFactory", data["vendor_id"])
        if vendor is None:
            raise ValueError("Vendor '{}' not found".format(data["vendor_id"]))
        po.VendorReference = vendor.Key
        po.Date = _net_date(date.fromisoformat(data["date"]))
        if data.get("expected_date"):
            po.GoodThroughDate = _net_date(date.fromisoformat(data["expected_date"]))
        if data.get("reference"):
            po.ReferenceNumber = data["reference"]

        for line_data in data.get("lines", []):
            line = po.AddLine()
            line.Description = _safe(line_data.get("description"), "")
            line.Quantity = _decimal(line_data.get("quantity", 1))
            line.UnitPrice = _decimal(line_data.get("unit_price", 0))
            if line_data.get("gl_account"):
                account = _find_entity(company, "AccountFactory", line_data["gl_account"])
                if account is not None:
                    line.AccountReference = account.Key
            if line_data.get("item_id"):
                item = _find_inventory_item(company, line_data["item_id"])
                if item is not None:
                    line.InventoryItemReference = item.Key

        _save_entity(po, "purchase order")
        logger.info("Purchase order created in Sage: %s", _entity_guid(po))
        return _purchase_order_to_dict(po, company)


def _purchase_order_to_dict(po, company) -> Dict[str, Any]:
    lines = []
    try:
        collection = po.PurchaseOrderLines
        for idx in range(collection.Count):
            line = collection[idx]
            lines.append({
                "line_no": idx + 1,
                "description": sdk_api.text(getattr(line, "Description", "")),
                "quantity": sdk_api.num(getattr(line, "Quantity", 0)),
                "unit_price": sdk_api.num(getattr(line, "UnitPrice", 0)),
                "item_id": sdk_api.reference_id(
                    company, getattr(line, "InventoryItemReference", None)),
            })
    except Exception as exc:
        logger.warning("Could not read PO lines for %s: %s", _entity_guid(po), exc)
    return {
        "sage_id": _entity_guid(po),
        "vendor_id": sdk_api.reference_id(company, getattr(po, "VendorReference", None)),
        "date": _py_date(po.Date),
        "expected_date": _py_date(getattr(po, "GoodThroughDate", None)),
        "reference": sdk_api.text(getattr(po, "ReferenceNumber", "")),
        "total_amount": sdk_api.num(po.Amount),
        "is_closed": bool(getattr(po, "IsClosed", False)),
        "lines": lines,
    }


# ── INVENTORY ITEMS ───────────────────────────────────────────────────────────
#
# Sage splits inventory across several concrete item types (StockItem,
# NonStockItem, ServiceItem, AssemblyItem, ...). InventoryItemFactory is the
# polymorphic one that returns them all, which is what a stock listing wants.

def sdk_get_inventory(limit: int = 1000) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_INVENTORY, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "InventoryItemFactory").List(), limit)
        return [_inventory_to_dict(i, company) for i in items]


def sdk_get_inventory_item(item_id: str) -> Optional[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return next((i for i in md.MOCK_INVENTORY if i["id"] == item_id), None)
    with _get_session().access() as company:
        item = _find_inventory_item(company, item_id)
        return _inventory_to_dict(item, company) if item is not None else None


def _find_inventory_item(company, item_id: str):
    for item in sdk_api.load_list(_factory(company, "InventoryItemFactory").List()):
        if sdk_api.text(getattr(item, "ID", "")) == item_id.strip():
            return item
    return None


def _inventory_to_dict(item, company) -> Dict[str, Any]:
    """
    Map a Sage inventory item.

    Two properties the old code used do not exist:
      * ``QuantityOnHand`` is a METHOD taking an as-of date, not a property.
      * ``SalesPrice`` does not exist — prices live in a PriceLevels list, of
        which level 1 is the standard sell price.
    Cost is not exposed on the item at all (it is a costing-method computation),
    so it is reported as 0.0 rather than guessed.
    """
    import System  # type: ignore[import]

    qty_on_hand = 0.0
    try:
        qty_on_hand = sdk_api.num(item.QuantityOnHand(System.DateTime.Now))
    except Exception as exc:
        logger.debug("QuantityOnHand unavailable for %s: %s",
                     getattr(item, "ID", "?"), exc)

    sales_price = 0.0
    try:
        levels = getattr(item, "PriceLevels", None)
        if levels is not None and levels.Count > 0:
            sales_price = sdk_api.num(levels[0].UnitPrice)
    except Exception:
        pass

    return {
        "id": sdk_api.text(getattr(item, "ID", "")),
        "description": sdk_api.text(getattr(item, "Description", "")),
        "item_type": type(item).__name__,
        "sales_price": sales_price,
        # Not exposed on the item — a costing-method computation in Sage.
        "cost": 0.0,
        "quantity_on_hand": qty_on_hand,
        "quantity_on_order": 0.0,
        "reorder_quantity": sdk_api.num(getattr(item, "ReorderQuantity", 0)),
        "minimum_stock": sdk_api.num(getattr(item, "MinimumStock", 0)),
        "sales_gl_account": sdk_api.reference_id(
            company, getattr(item, "SalesAccountReference", None)),
        "cogs_gl_account": sdk_api.reference_id(
            company, getattr(item, "COGSAccountReference", None)),
        "inventory_gl_account": sdk_api.reference_id(
            company, getattr(item, "InventoryAccountReference", None)),
        "is_active": not bool(getattr(item, "IsInactive", False)),
        "is_taxable": bool(getattr(item, "IsTaxable", False)),
        "unit_of_measure": "",
        "weight": sdk_api.num(getattr(item, "Weight", 0)),
        "part_number": sdk_api.text(getattr(item, "PartNumber", "")),
        "upc": sdk_api.text(getattr(item, "UPC", "")),
        "location": sdk_api.text(getattr(item, "Location", "")),
        "category": sdk_api.text(getattr(item, "Category", "")),
    }


# ── CHART OF ACCOUNTS ─────────────────────────────────────────────────────────

def sdk_get_accounts(limit: int = 1000) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_ACCOUNTS, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "AccountFactory").List(), limit)
        return [_account_to_dict(a) for a in items]


def _account_to_dict(acct) -> Dict[str, Any]:
    """
    Map a Sage Account.

    ``CurrentBalance`` does not exist; the balance comes from
    ``GetEndingBalance(asOf)``.
    """
    import System  # type: ignore[import]

    balance = 0.0
    try:
        balance = sdk_api.num(acct.GetEndingBalance(System.DateTime.Now))
    except Exception as exc:
        logger.debug("GetEndingBalance failed for %s: %s",
                     getattr(acct, "ID", "?"), exc)

    return {
        "id": sdk_api.text(getattr(acct, "ID", "")),
        "description": sdk_api.text(getattr(acct, "Description", "")),
        "account_type": str(getattr(acct, "Classification", "")),
        "balance": balance,
        "is_active": not bool(getattr(acct, "IsInactive", False)),
    }


# ── EMPLOYEES ─────────────────────────────────────────────────────────────────

def sdk_get_employees(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_EMPLOYEES, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "EmployeeFactory").List(), limit)
        return [_employee_to_dict(e) for e in items]


def _employee_to_dict(emp) -> Dict[str, Any]:
    """
    Map a Sage Employee.

    The SDK's Employee is far thinner than the old code assumed: there is no
    address, hire date, pay type, pay frequency or department. Only ID, Name,
    Email, PhoneNumbers, IsInactive and IsSalesRepresentative are exposed.
    Payroll detail is not reachable through this API at all.
    """
    name = sdk_api.text(getattr(emp, "Name", ""))
    first, _, last = name.partition(" ")
    return {
        "id": sdk_api.text(getattr(emp, "ID", "")),
        "name": name,
        "first_name": first,
        "last_name": last,
        "email": sdk_api.text(getattr(emp, "Email", "")),
        "phone": sdk_api.phone_at(getattr(emp, "PhoneNumbers", None), 0),
        "is_active": not bool(getattr(emp, "IsInactive", False)),
        "is_sales_rep": bool(getattr(emp, "IsSalesRepresentative", False)),
    }


# ── CUSTOMER RECEIPTS (Payments Received) ─────────────────────────────────────

def sdk_get_customer_receipts(
    customer_id: Optional[str] = None,
    from_date: Optional[date] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        data = md.MOCK_PAYMENTS
        if customer_id:
            data = [p for p in data if p.get("customer_id") == customer_id]
        return md.paginate(data, limit, 0)

    with _get_session().access() as company:
        result: List[Dict[str, Any]] = []
        for receipt in sdk_api.load_list(_factory(company, "ReceiptFactory").List()):
            if len(result) >= limit:
                break
            record = _receipt_to_dict(receipt, company)
            if customer_id and record["customer_id"] != customer_id.strip():
                continue
            if from_date and record["date"] and record["date"] < str(from_date):
                continue
            result.append(record)
        return result


def sdk_apply_customer_receipt(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Record a customer payment, optionally applied to a specific invoice.

    Applying to an invoice uses ``Receipt.AddInvoiceLine(transaction)`` — the
    invoice entity itself, not an ID — then sets ``AmountPaid`` on the returned
    line. The old code iterated a non-existent ``ApplyToInvoices`` property.
    """
    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": "RCPT-MOCK-{}".format(_uuid.uuid4().hex[:6].upper()), **data}
        md.MOCK_PAYMENTS.append(record)
        logger.info("[MOCK] Receipt applied: customer=%s amount=%s",
                    data.get("customer_id"), data.get("amount"))
        return record

    with _get_session().access() as company:
        receipt = _factory(company, "ReceiptFactory").Create()
        customer = _find_entity(company, "CustomerFactory", data["customer_id"])
        if customer is None:
            raise ValueError("Customer '{}' not found".format(data["customer_id"]))

        receipt.CustomerReference = customer.Key
        receipt.Date = _net_date(date.fromisoformat(data["date"]))
        if data.get("reference"):
            receipt.ReferenceNumber = data["reference"]
        if data.get("deposit_ticket_id"):
            receipt.DepositTicketID = data["deposit_ticket_id"]

        amount = float(data["amount"])
        invoice_id = data.get("invoice_id")

        if invoice_id:
            target = None
            wanted = str(invoice_id).strip()
            for inv in sdk_api.load_list(_factory(company, "SalesInvoiceFactory").List()):
                if _entity_guid(inv) == wanted or \
                        sdk_api.text(inv.ReferenceNumber) == wanted:
                    target = inv
                    break
            if target is None:
                raise ValueError(
                    "Invoice '{}' not found — cannot apply the receipt to it."
                    .format(invoice_id)
                )
            line = receipt.AddInvoiceLine(target)
            line.AmountPaid = _decimal(amount)
        else:
            # Unapplied receipt: goes to the customer's account as a credit.
            line = receipt.AddSalesLine()
            line.Amount = _decimal(amount)

        _save_entity(receipt, "receipt for {}".format(data["customer_id"]))
        logger.info(
            "Customer receipt applied: customer=%s amount=%.2f",
            data["customer_id"], amount,
        )
        return _receipt_to_dict(receipt, company)


def _receipt_to_dict(r, company) -> Dict[str, Any]:
    return {
        "sage_id": _entity_guid(r),
        "customer_id": sdk_api.reference_id(company, getattr(r, "CustomerReference", None)),
        "date": _py_date(r.Date),
        # Receipt exposes Amount, not AmountReceived.
        "amount": sdk_api.num(getattr(r, "Amount", 0)),
        "reference": sdk_api.text(getattr(r, "ReferenceNumber", "")),
        "receipt_number": sdk_api.text(getattr(r, "ReceiptNumber", "")),
        "payment_method": sdk_api.text(getattr(r, "PaymentMethod", "")),
        "deposit_ticket_id": sdk_api.text(getattr(r, "DepositTicketID", "")),
    }


# ── VENDOR BILLS (Accounts Payable) ──────────────────────────────────────────

def sdk_get_vendor_invoices(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_VENDOR_BILLS, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "PurchaseInvoiceFactory").List(), limit)
        return [_vendor_invoice_to_dict(b, company) for b in items]


def sdk_create_vendor_invoice(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    NOT SUPPORTED by the Sage 50 2013 SDK.

    ``PurchaseInvoice`` exposes no ``Save()`` — verified by reflection against
    2013.0.0.826, where its only methods are MarkForDeletion and Validate. Sage
    made vendor bills read-only through this API. Enter them in Sage directly,
    or record the liability as a general journal entry.

    This raises rather than failing silently: a "successful" call that wrote
    nothing would leave SynBot believing a payable exists that Sage has never
    heard of.
    """
    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": "BILL-MOCK-{}".format(_uuid.uuid4().hex[:6].upper()),
                  "is_paid": False, **data}
        md.MOCK_VENDOR_BILLS.append(record)
        logger.info("[MOCK] Vendor invoice created")
        return record

    raise NotImplementedError(
        "Creating vendor bills is not supported by the Sage 50 2013 SDK — "
        "PurchaseInvoice has no Save() method. Enter the bill in Sage 50, or "
        "post the liability via POST /journal instead."
    )


def _vendor_invoice_to_dict(bill, company) -> Dict[str, Any]:
    total = sdk_api.num(getattr(bill, "Amount", 0))
    due = sdk_api.num(getattr(bill, "AmountDue", 0))
    return {
        "sage_id": _entity_guid(bill),
        "vendor_id": sdk_api.reference_id(company, getattr(bill, "VendorReference", None)),
        "date": _py_date(bill.Date),
        "due_date": _py_date(getattr(bill, "DateDue", None)),
        "reference": sdk_api.text(getattr(bill, "ReferenceNumber", "")),
        "total_amount": total,
        "amount_paid": round(total - due, 2),
        "amount_due": due,
        "is_paid": due <= 0.005,
        "is_posted": bool(getattr(bill, "IsPosted", False)),
    }


# ── GENERAL JOURNAL ENTRIES ───────────────────────────────────────────────────

def sdk_get_journal_entries(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        data = md.MOCK_JOURNAL
        if from_date:
            data = [j for j in data if j.get("date", "") >= str(from_date)]
        if to_date:
            data = [j for j in data if j.get("date", "") <= str(to_date)]
        return md.paginate(data, limit, 0)

    with _get_session().access() as company:
        result: List[Dict[str, Any]] = []
        factory = _factory(company, "GeneralJournalEntryFactory")
        for entry in sdk_api.load_list(factory.List()):
            if len(result) >= limit:
                break
            entry_date = _py_date(entry.Date)
            if from_date and entry_date and entry_date < str(from_date):
                continue
            if to_date and entry_date and entry_date > str(to_date):
                continue
            result.append(_journal_entry_to_dict(entry, company))
        return result


def sdk_create_journal_entry(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a general journal entry.

    Sage models a journal line as a single SIGNED ``Amount`` — there are no
    separate Debit and Credit properties. Convention: **positive is a debit,
    negative is a credit**. The wire format keeps debit/credit for the caller's
    convenience and converts here.
    """
    total_debit = sum(float(l.get("debit", 0)) for l in data.get("lines", []))
    total_credit = sum(float(l.get("credit", 0)) for l in data.get("lines", []))
    if round(total_debit, 4) != round(total_credit, 4):
        raise ValueError(
            "Journal entry does not balance: debits={:.4f} credits={:.4f}"
            .format(total_debit, total_credit)
        )

    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": "JNL-MOCK-{}".format(_uuid.uuid4().hex[:6].upper()), **data}
        md.MOCK_JOURNAL.append(record)
        logger.info("[MOCK] Journal entry created")
        return record

    with _get_session().access() as company:
        entry = _factory(company, "GeneralJournalEntryFactory").Create()
        entry.Date = _net_date(date.fromisoformat(data["date"]))
        if data.get("reference"):
            entry.ReferenceNumber = data["reference"]

        for line_data in data.get("lines", []):
            line = entry.AddLine()
            account = _find_entity(company, "AccountFactory", line_data["account_id"])
            if account is None:
                raise ValueError(
                    "GL account '{}' not found in Sage".format(line_data["account_id"])
                )
            line.AccountReference = account.Key
            debit = float(_safe(line_data.get("debit"), 0) or 0)
            credit = float(_safe(line_data.get("credit"), 0) or 0)
            line.Amount = _decimal(debit - credit)
            line.Description = _safe(line_data.get("description"), "")

        _save_entity(entry, "journal entry")
        logger.info("General journal entry created in Sage: %s", _entity_guid(entry))
        return _journal_entry_to_dict(entry, company)


def _journal_entry_to_dict(entry, company) -> Dict[str, Any]:
    lines = []
    try:
        collection = entry.GeneralJournalEntryLines
        for idx in range(collection.Count):
            line = collection[idx]
            amount = sdk_api.num(getattr(line, "Amount", 0))
            lines.append({
                "account_id": sdk_api.reference_id(
                    company, getattr(line, "AccountReference", None)),
                # Signed Amount split back out; positive is a debit.
                "debit": round(amount, 2) if amount > 0 else 0.0,
                "credit": round(-amount, 2) if amount < 0 else 0.0,
                "description": sdk_api.text(getattr(line, "Description", "")),
            })
    except Exception as exc:
        logger.warning("Could not read journal lines for %s: %s",
                       _entity_guid(entry), exc)
    return {
        "sage_id": _entity_guid(entry),
        "date": _py_date(entry.Date),
        "reference": sdk_api.text(getattr(entry, "ReferenceNumber", "")),
        "is_posted": bool(getattr(entry, "IsPosted", False)),
        "lines": lines,
    }


# ── COMPANY INFORMATION ───────────────────────────────────────────────────────

def sdk_get_company_info() -> Dict[str, Any]:
    """
    Return what the SDK exposes about the company.

    There is no ``CompanyInformation`` object. The identifying metadata lives on
    ``Company.CompanyIdentifier``; the address, phone, tax ID and fiscal year
    that the old code returned are simply not reachable through this API. Fields
    that cannot be sourced are returned empty rather than fabricated, and
    ``_unavailable`` names them so a consumer can tell "empty" from "not
    supported".
    """
    if _is_mock():
        import mock_data as md
        return md.MOCK_COMPANY

    with _get_session().access() as company:
        cid = company.CompanyIdentifier
        return {
            "name": sdk_api.text(getattr(cid, "CompanyName", "")),
            "path": sdk_api.text(getattr(cid, "Path", "")),
            "database_name": sdk_api.text(getattr(cid, "DatabaseName", "")),
            "server_name": sdk_api.text(getattr(cid, "ServerName", "")),
            "schema_version": sdk_api.text(getattr(cid, "SchemaVersion", "")),
            "guid": str(getattr(cid, "Guid", "")),
            "address1": "", "address2": "", "city": "", "state": "",
            "zip": "", "country": "", "phone": "", "fax": "", "email": "",
            "website": "", "tax_id": "", "fiscal_year_start": None,
            "_unavailable": [
                "address", "phone", "fax", "email", "website", "tax_id",
                "fiscal_year_start",
            ],
            "_note": "Sage 50 2013 SDK exposes no CompanyInformation object; "
                     "these fields are only in the Sage UI and the ODBC "
                     "COMPANY table.",
        }


# ── PAYROLL ───────────────────────────────────────────────────────────────────

def sdk_get_payroll_checks(
    from_date: Optional[date] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """
    NOT AVAILABLE through the Sage 50 2013 SDK.

    There is no payroll factory on Company.Factories — verified against the full
    factory list in 2013.0.0.826. Payroll must be read over ODBC (PAYROLL.DAT)
    if it is needed.

    Returns an empty list rather than raising, because payroll is a
    nice-to-have reporting feed rather than part of the invoice sync path, and
    a hard failure here would take down callers that merely list it.
    """
    if _is_mock():
        import mock_data as md
        data = md.MOCK_PAYROLL
        if from_date:
            data = [p for p in data if p.get("date", "") >= str(from_date)]
        return md.paginate(data, limit, 0)

    logger.warning(
        "Payroll is not exposed by the Sage 50 2013 SDK — returning []. "
        "Use the ODBC PAYROLL table if payroll data is required."
    )
    return []


# ── QUOTES ────────────────────────────────────────────────────────────────────

def sdk_get_quotes(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_QUOTES, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "QuoteFactory").List(), limit)
        return [{
            "sage_id": _entity_guid(q),
            "customer_id": sdk_api.reference_id(
                company, getattr(q, "CustomerReference", None)),
            "date": _py_date(q.Date),
            "good_through_date": _py_date(getattr(q, "GoodThroughDate", None)),
            "total_amount": sdk_api.num(q.Amount),
            "reference": sdk_api.text(getattr(q, "ReferenceNumber", "")),
        } for q in items]


# ── JOBS (Job Costing) ────────────────────────────────────────────────────────

def sdk_get_jobs(limit: int = 500) -> List[Dict[str, Any]]:
    """
    List job-costing records.

    Sage's Job entity is minimal — ID, Description, IsInactive. The start date,
    projected end date, status and revenue figures the old code returned do not
    exist on it and are omitted rather than faked.
    """
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_JOBS, limit, 0)
    with _get_session().access() as company:
        items = sdk_api.load_list(_factory(company, "JobFactory").List(), limit)
        return [{
            "id": sdk_api.text(getattr(j, "ID", "")),
            "description": sdk_api.text(getattr(j, "Description", "")),
            "is_active": not bool(getattr(j, "IsInactive", False)),
        } for j in items]


# ── write helpers ────────────────────────────────────────────────────────────

def _decimal(value: Any):
    """
    Convert a Python number to System.Decimal.

    Sage money and quantity properties are System.Decimal. Assigning a Python
    float works through pythonnet for small values but is lossy — round-tripping
    a price like 19.99 through binary floating point can land a cent out, which
    on a posted invoice is a real accounting discrepancy. Going via str keeps
    the decimal exact.
    """
    import System  # type: ignore[import]
    if value is None:
        return System.Decimal(0)
    return System.Decimal.Parse(
        "{:.6f}".format(float(value)),
        System.Globalization.CultureInfo.InvariantCulture,
    )


def _find_entity(company, factory_name: str, entity_id: str):
    """Find an entity by its human-readable ID. None when absent."""
    if not entity_id:
        return None
    wanted = str(entity_id).strip()
    for item in sdk_api.load_list(_factory(company, factory_name).List()):
        if sdk_api.text(getattr(item, "ID", "")) == wanted:
            return item
    return None


def _save_entity(entity, description: str) -> None:
    """
    Validate then save, surfacing Sage's own validation problems.

    ``Save()`` on an invalid entity throws a generic exception whose message
    rarely says which field is wrong. ``Validate(ValidationProblemList)`` fills
    a list with the specific problems, which is the difference between a
    fixable error report and "save failed".
    """
    try:
        problems = _new_validation_problem_list()
        if problems is not None:
            if not entity.Validate(problems):
                detail = _describe_problems(problems)
                raise ValueError(
                    "Sage rejected {}: {}".format(description, detail)
                )
        entity.Save()
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "Saving {} to Sage failed: {}".format(description, exc)
        ) from exc


def _new_validation_problem_list():
    """
    A ValidationProblemList for Validate() to populate.

    Note the namespace: ValidationProblemList is in ``Sage.Peachtree.API``, not
    in ``Sage.Peachtree.API.Validations`` where the concrete problem subclasses
    (MissingValueProblem, DuplicateValueProblem, ...) live.
    """
    try:
        from Sage.Peachtree.API import ValidationProblemList  # type: ignore
        return ValidationProblemList()
    except Exception as exc:
        logger.debug("ValidationProblemList unavailable: %s", exc)
        return None


def _describe_problems(problems) -> str:
    """Render Sage's validation problems as 'PropertyName: Message' pairs."""
    try:
        parts = []
        for i in range(min(problems.Count, 10)):
            problem = problems[i]
            field = sdk_api.text(getattr(problem, "PropertyName", ""))
            message = sdk_api.text(getattr(problem, "Message", "")) or str(problem)
            parts.append("{}: {}".format(field, message) if field else message)
        return "; ".join(parts) or "no detail supplied"
    except Exception:
        return "no detail supplied"
