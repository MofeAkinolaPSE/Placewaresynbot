from .local_db import LocalDBClient
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv
import yaml
import logging
import datetime
import uuid
import hashlib
import json
from collections import Counter
import threading
import time
from .constants import (
    TABLE_LEADS,
    TABLE_ORDERS,
    TABLE_TRACKING,
    TABLE_AUDIT_LOGS,
    TABLE_IMPORT_JOBS,
    TABLE_IMPORT_REJECTIONS,
    TABLE_KPI_PROMOTIONS,
    TABLE_DATA_POLICIES,
    TABLE_USERS,
    TABLE_REFRESH_TOKENS,
    TABLE_PROJECTS,
    TABLE_SCOPE_ITEMS,
    TABLE_COST_ITEMS,
    TABLE_RISK_REGISTER,
    TABLE_CHANGE_REQUESTS,
    TABLE_PROCUREMENT_SHIPMENTS,
    TABLE_PROCUREMENT_SHIPMENT_EVENTS,
    # Snapshot tables
    # Using literal names defined in migration for clarity
    TABLE_QNA,
    TABLE_STOCK_CACHE,
    TABLE_WEBHOOK_IDEMPOTENCY,  # <-- Added missing import
    ENV_SUPABASE_URL,
    ENV_SUPABASE_KEY,
    ENV_EMAIL_FROM,
    ENV_EMAIL_PASS,
    BOT_BRAND,
    BOT_NAME,
    AT_REST_KEY,
)

load_dotenv()

SUPABASE_URL = os.getenv(ENV_SUPABASE_URL)
SUPABASE_KEY = os.getenv(ENV_SUPABASE_KEY)
EMAIL_FROM = os.getenv(ENV_EMAIL_FROM)
EMAIL_PASS = os.getenv(ENV_EMAIL_PASS)

# Local DB client for PostgreSQL access
db = LocalDBClient(os.getenv('DATABASE_URL'))


def get_psycopg_dsn() -> str:
    """Return a psycopg-compatible DSN string.

    Preference order:
    1. `DATABASE_URL` environment variable
    2. Build from `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`
    3. Fall back to Supabase URL if present (not recommended)
    """
    # Prefer explicit DATABASE_URL
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url

    user = os.getenv("POSTGRES_USER") or os.getenv("PGUSER") or "postgres"
    password = os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD") or ""
    db = os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE") or "postgres"
    host = os.getenv("POSTGRES_HOST") or os.getenv("PGHOST") or "localhost"
    port = os.getenv("POSTGRES_PORT") or os.getenv("PGPORT") or "5432"
    if password:
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return f"postgresql://{user}@{host}:{port}/{db}"


class AuthStoreUnavailableError(RuntimeError):
    """Raised when auth persistence storage is temporarily unavailable."""

config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
try:
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    email_config = config.get("email", {})
    recipients = email_config.get("recipients", {})
except Exception as e:
    logging.error(f"Error loading config.yaml: {e}")
    config = {}
    recipients = {}

def send_email_background(msg: MIMEText, recipient: str, max_retries: int = 3, backoff_factor: int = 2) -> None:
    """Send email in a background thread with retries and exponential backoff.

    - `msg` should be a `MIMEText` instance. The `To` header will be set by the worker.
    - Retries are logged; sensitive credentials are not logged.
    """
    def _worker(message: MIMEText, to_addr: str):
        tries = 0
        while tries < max_retries:
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                    server.login(EMAIL_FROM, EMAIL_PASS)
                    message["To"] = to_addr
                    server.send_message(message)
                logging.info(f"Email sent to %s; subject=%s", to_addr, message.get("Subject"))
                # record success in email events table
                try:
                    db.table("placeware_email_events").insert({
                        "msg_subject": message.get("Subject"),
                        "recipient": to_addr,
                        "status": "sent",
                        "attempts": tries + 1,
                        "updated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                    }).execute()
                except Exception:
                    pass
                return
            except Exception as e:
                tries += 1
                logging.warning("Email send attempt %d failed for %s: %s", tries, to_addr, e)
                # record attempt/failure
                try:
                    db.table("placeware_email_events").insert({
                        "msg_subject": message.get("Subject"),
                        "recipient": to_addr,
                        "status": "failed",
                        "attempts": tries,
                        "last_error": str(e),
                        "updated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                    }).execute()
                except Exception:
                    pass
                sleep_seconds = backoff_factor ** (tries - 1)
                time.sleep(sleep_seconds)
        logging.error("Failed to send email to %s after %d attempts", to_addr, max_retries)
        try:
            db.table("placeware_email_events").insert({
                "msg_subject": message.get("Subject"),
                "recipient": to_addr,
                "status": "failed",
                "attempts": max_retries,
                "updated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            }).execute()
        except Exception:
            pass

    thread = threading.Thread(target=_worker, args=(msg, recipient), daemon=True)
    thread.start()

def _aes_encrypt(plaintext: str) -> str:
    """Encrypt plaintext with AES-256-GCM using AT_REST_KEY.

    Returns base64(nonce|ciphertext). If key missing or error, returns plaintext.
    """
    try:
        import base64, os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if not AT_REST_KEY:
            return plaintext
        key = base64.b64decode(AT_REST_KEY)
        if len(key) not in (16, 24, 32):
            # Expect 32 bytes for AES-256, fallback to plaintext
            return plaintext
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        blob = nonce + ct
        return base64.b64encode(blob).decode("utf-8")
    except Exception as e:
        logging.error(f"AES encrypt failed: {e}")
        return plaintext


def _encrypt_sensitive_fields(data: dict) -> dict:
    """Encrypt sensitive fields in the lead payload for at-rest protection."""
    out = dict(data)
    for f in ("email", "phone", "message"):
        v = out.get(f)
        if isinstance(v, str) and v:
            out[f] = _aes_encrypt(v)
    return out


def store_lead(lead_data):
    """Insert a lead and send notification email.

    Returns the new lead ID or None on failure.
    """
    try:
        enc = _encrypt_sensitive_fields(lead_data)
        result = db.table(TABLE_LEADS).insert(enc).execute()
        lead_id = result.data[0]["id"]
        try:
            service = str(lead_data.get("service") or "marketing").lower().strip()
            recipient = recipients.get(service, recipients.get("marketing", EMAIL_FROM))
            if EMAIL_FROM and EMAIL_PASS and recipient:
                msg = MIMEText(
                    f"New lead for {BOT_BRAND}: {lead_data['name']}\nEmail: {lead_data['email']}\nPhone: {lead_data['phone']}\nMessage: {lead_data['message']}\nService: {lead_data.get('service', 'None')}"
                )
                msg["Subject"] = f"New Lead #{lead_id} via {BOT_NAME}"
                msg["From"] = EMAIL_FROM
                # Send asynchronously with retries
                send_email_background(msg, recipient)
            else:
                logging.warning("Lead email skipped: missing email credentials or recipient")
        except Exception as email_err:
            logging.error(f"Lead email notification failed: {email_err}")
        return lead_id
    except Exception as e:
        logging.error(f"Error storing lead or sending email: {e}")
        return None


def _build_order_email_payload(
    *,
    order_id: str,
    tracking_id: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None,
    items: list[dict],
    notes: str | None,
    source: str,
    lead_id: int | None,
) -> MIMEText:
    item_lines = "\n".join(
        [f"- {str(i.get('sku') or '').strip()}: {int(i.get('quantity') or 0)}" for i in items]
    ) or "- No items"
    body = (
        f"New order via {BOT_NAME}\n"
        f"Order ID: {order_id}\n"
        f"Tracking ID: {tracking_id}\n"
        f"Source: {source}\n"
        f"Lead ID: {lead_id if lead_id is not None else 'N/A'}\n"
        f"Customer: {customer_name}\n"
        f"Email: {customer_email}\n"
        f"Phone: {customer_phone or 'N/A'}\n"
        f"Items:\n{item_lines}\n"
        f"Notes: {notes or 'N/A'}\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"New Order #{order_id} via {BOT_NAME}"
    msg["From"] = EMAIL_FROM
    return msg


def _notify_order(order_record: dict) -> None:
    try:
        recipient = (
            recipients.get("orders")
            or recipients.get("sales")
            or recipients.get("marketing")
            or EMAIL_FROM
        )
        if not (EMAIL_FROM and EMAIL_PASS and recipient):
            logging.warning("Order email skipped: missing email credentials or recipient")
            return
        msg = _build_order_email_payload(
            order_id=str(order_record.get("order_id") or ""),
            tracking_id=str(order_record.get("tracking_id") or ""),
            customer_name=str(order_record.get("customer_name") or "Customer"),
            customer_email=str(order_record.get("customer_email") or ""),
            customer_phone=order_record.get("customer_phone"),
            items=order_record.get("items") or [],
            notes=order_record.get("notes"),
            source=str(order_record.get("source") or "direct"),
            lead_id=order_record.get("lead_id"),
        )
        # Send asynchronously with retries
        send_email_background(msg, recipient)
    except Exception as e:
        logging.error(f"Order notification failed: {e}")


def store_order(order_data: dict) -> dict | None:
    """Persist order and initial tracking record.

    Returns a normalized record payload with IDs or None on failure.
    """
    try:
        order_id = str(uuid.uuid4())
        tracking_id = str(uuid.uuid4())
        now_iso = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        source = str(order_data.get("source") or "direct").strip().lower()
        lead_id = order_data.get("lead_id")

        core_payload = {
            "id": order_id,
            "customer_name": order_data.get("customer_name"),
            "customer_email": order_data.get("customer_email"),
            "customer_phone": order_data.get("customer_phone"),
            "items": order_data.get("items") or [],
            "notes": order_data.get("notes"),
            "status": "received",
        }
        extended_payload = {
            **core_payload,
            "source": source,
            "lead_id": lead_id,
        }

        try:
            db.table(TABLE_ORDERS).insert(extended_payload).execute()
        except Exception:
            db.table(TABLE_ORDERS).insert(core_payload).execute()

        tracking_payload = {
            "id": tracking_id,
            "order_id": order_id,
            "status": "received",
            "last_update": now_iso,
            "eta": order_data.get("eta") or "pending",
        }
        db.table(TABLE_TRACKING).insert(tracking_payload).execute()

        out = {
            "order_id": order_id,
            "tracking_id": tracking_id,
            "status": "received",
            "customer_name": order_data.get("customer_name"),
            "customer_email": order_data.get("customer_email"),
            "customer_phone": order_data.get("customer_phone"),
            "items": order_data.get("items") or [],
            "notes": order_data.get("notes"),
            "source": source,
            "lead_id": lead_id,
            "walk_in_agent": order_data.get("walk_in_agent"),
            "walk_in_location": order_data.get("walk_in_location"),
        }
        _notify_order(out)
        return out
    except Exception as e:
        logging.error(f"store_order failed: {e}")
        return None


def get_tracking(tracking_id: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_TRACKING)
            .select("id,order_id,status,last_update,eta")
            .eq("id", tracking_id)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        return data[0] if data else None
    except Exception as e:
        logging.error(f"get_tracking failed: {e}")
        return None


def is_webhook_idempotent(idempotency_key: str) -> bool:
    """Check if an idempotency key has already been recorded."""
    try:
        if not idempotency_key:
            return False
        resp = (
            db.table(TABLE_WEBHOOK_IDEMPOTENCY)
            .select("id")
            .eq("idempotency_key", idempotency_key)
            .limit(1)
            .execute()
        )
        return bool(resp.data)
    except Exception as e:
        logging.error(f"is_webhook_idempotent failed: {e}")
        return False


def record_webhook_idempotency(idempotency_key: str, tracking_id: str | None, provider: str | None, payload: dict | None) -> bool:
    """Persist an idempotency record to speed up duplicate checks.

    Uses upsert to avoid race errors.
    """
    try:
        if not idempotency_key:
            return False
        row = {
            "idempotency_key": idempotency_key,
            "tracking_id": tracking_id,
            "provider": provider,
            "payload": payload or {},
        }
        db.table(TABLE_WEBHOOK_IDEMPOTENCY).upsert(row).execute()
        return True
    except Exception as e:
        logging.error(f"record_webhook_idempotency failed: {e}")
        return False


def _derive_audit_taxonomy(event_type: str, details: dict) -> dict:
    et = (event_type or "").lower()
    if et.startswith("auth_"):
        event_class = "security"
    elif et.startswith("sage_") or et.endswith("_import"):
        event_class = "data_ingestion"
    elif et.startswith("user_"):
        event_class = "identity"
    elif et.startswith("intent_") or et.startswith("workflow_"):
        event_class = "workflow"
    elif et.startswith("ops_") or et.startswith("hr_") or et.startswith("crm_"):
        event_class = "analytics"
    else:
        event_class = "system"

    outcome = "failed" if "fail" in et or "error" in et else "success"
    action = event_type
    reason_code = details.get("reason") if isinstance(details, dict) else None

    actor_id = None
    actor_role = None
    if isinstance(details, dict):
        actor_id = details.get("user_id") or details.get("admin") or details.get("creator")
        user_obj = details.get("user")
        if not actor_id and isinstance(user_obj, dict):
            actor_id = user_obj.get("sub") or user_obj.get("id")
            roles = user_obj.get("roles") or []
            if isinstance(roles, list) and roles:
                actor_role = roles[0]
        if not actor_role:
            role_candidate = details.get("role")
            if isinstance(role_candidate, str):
                actor_role = role_candidate

    subject_type = None
    subject_id = None
    if isinstance(details, dict):
        if details.get("target_user_id"):
            subject_type = "user"
            subject_id = details.get("target_user_id")
        elif details.get("job_id"):
            subject_type = "import_job"
            subject_id = details.get("job_id")
        elif details.get("batch_id"):
            subject_type = "import_batch"
            subject_id = details.get("batch_id")

    return {
        "event_class": event_class,
        "action": action,
        "outcome": outcome,
        "reason_code": reason_code,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "subject_type": subject_type,
        "subject_id": subject_id,
    }


def _compute_signature_hash_ref(
    *,
    event_type: str,
    actor_id: str | None,
    subject_type: str | None,
    subject_id: str | None,
    approval_reason: str | None,
    attestation_text: str,
    details: dict,
) -> str:
    canonical = {
        "event_type": event_type,
        "actor_id": actor_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "approval_reason": approval_reason,
        "attestation_text": attestation_text,
        "details": details,
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit_event(
    event_type: str,
    details: dict | None = None,
    *,
    event_class: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    reason_code: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    trace_id: str | None = None,
    approval_reason: str | None = None,
    attestation_text: str | None = None,
    signature_hash_ref: str | None = None,
) -> None:
    details = details or {}
    derived = _derive_audit_taxonomy(event_type, details)
    try:
        resolved_actor_id = actor_id or derived.get("actor_id")
        resolved_subject_type = subject_type or derived.get("subject_type")
        resolved_subject_id = subject_id or derived.get("subject_id")
        resolved_signature_hash = signature_hash_ref
        if attestation_text and not resolved_signature_hash:
            resolved_signature_hash = _compute_signature_hash_ref(
                event_type=event_type,
                actor_id=resolved_actor_id,
                subject_type=resolved_subject_type,
                subject_id=resolved_subject_id,
                approval_reason=approval_reason,
                attestation_text=attestation_text,
                details=details,
            )

        payload = {
            "event_type": event_type,
            "event_class": event_class or derived.get("event_class") or "system",
            "action": action or derived.get("action") or event_type,
            "outcome": outcome or derived.get("outcome") or "success",
            "reason_code": reason_code or derived.get("reason_code"),
            "actor_id": resolved_actor_id,
            "actor_role": actor_role or derived.get("actor_role"),
            "subject_type": resolved_subject_type,
            "subject_id": resolved_subject_id,
            "trace_id": trace_id or str(uuid.uuid4()),
            "approval_reason": approval_reason,
            "attestation_text": attestation_text,
            "signature_hash_ref": resolved_signature_hash,
            "details": details,
        }
        db.table(TABLE_AUDIT_LOGS).insert(payload).execute()
    except Exception as e:
        logging.error(f"Audit log insert failed: {e}")


def upsert_stock_cache(rows: list[dict]) -> int:
    """Upsert stock snapshot cache for quick reads.

    Returns number of rows processed.
    """
    try:
        if not rows:
            return 0
        db.table(TABLE_STOCK_CACHE).upsert(rows).execute()
        return len(rows)
    except Exception as e:
        logging.error(f"Stock cache upsert failed: {e}")
        return 0


# ---- Snapshot persistence helpers ------------------------------------------

class SnapshotInsertError(Exception):
    """Raised when snapshot insert fails after retries."""
    def __init__(self, table: str, row_count: int, original_error: Exception):
        self.table = table
        self.row_count = row_count
        self.original_error = original_error
        super().__init__(f"Failed to insert {row_count} rows into {table}: {original_error}")


def insert_snapshot(table: str, batch_id: str, imported_at: str, rows: list[dict]) -> int:
    """Insert rows into a snapshot table with batch metadata.

    Returns number of inserted rows.
    Raises SnapshotInsertError if insert fails after retries.
    """
    if not rows:
        logging.debug(f"insert_snapshot: no rows to insert into {table}")
        return 0
    
    enriched = []
    for r in rows:
        x = dict(r)
        x["batch_id"] = batch_id
        x["imported_at"] = imported_at
        enriched.append(x)
    
    logging.info(f"insert_snapshot: attempting to insert {len(enriched)} rows into {table}")
    
    # Simple retry for transient failures
    max_attempts = 3
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            db.table(table).insert(enriched).execute()
            logging.info(f"insert_snapshot: successfully inserted {len(enriched)} rows into {table}")
            return len(enriched)
        except Exception as e:
            last_err = e
            logging.warning(f"insert_snapshot: attempt {attempt}/{max_attempts} failed for {table}: {e}")
            if attempt < max_attempts:
                import time
                time.sleep(0.5 * attempt)  # Exponential backoff
    
    # All retries exhausted - raise exception instead of silently returning 0
    logging.error(f"insert_snapshot: FAILED to insert {len(enriched)} rows into {table} after {max_attempts} attempts. Last error: {last_err}")
    raise SnapshotInsertError(table, len(enriched), last_err)


def create_import_job(
    domain: str,
    batch_id: str,
    imported_at: str,
    metadata: dict | None = None,
    idempotency_key: str | None = None,
    status: str = "running",
) -> str | None:
    """Create a new import job control record and return job id."""
    try:
        policy = get_import_policy(domain)
        retention_days = int(policy.get("retention_days") or 2555)
        imported_dt = _parse_iso_datetime(imported_at)
        retention_expires_at = (imported_dt + datetime.timedelta(days=retention_days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        payload = {
            "domain": domain,
            "batch_id": batch_id,
            "imported_at": imported_at,
            "status": status,
            "schema_version": policy.get("schema_version") or "2026.1",
            "policy_version": policy.get("policy_version") or "2026.1",
            "retention_days": retention_days,
            "retention_expires_at": retention_expires_at,
            "metadata": metadata or {},
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        resp = (
            db.table(TABLE_IMPORT_JOBS)
            .insert(payload)
            .execute()
        )
        data = resp.data or []
        return data[0].get("id") if data else None
    except Exception as e:
        logging.error(f"create_import_job failed: {e}")
        return None


def _parse_iso_datetime(value: str) -> datetime.datetime:
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)


def get_import_policy(domain: str) -> dict:
    """Resolve import governance policy for a domain with DB-first + fallback defaults."""
    try:
        resp = (
            db.table(TABLE_DATA_POLICIES)
            .select("domain,retention_days,schema_version,policy_version,controls_config")
            .eq("domain", domain)
            .eq("active", True)
            .order("effective_from", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if rows:
            return rows[0]
    except Exception as e:
        logging.info(f"get_import_policy fallback for {domain}: {e}")

    controls_defaults = {
        "severity_weights": {"info": 1, "warning": 2, "error": 4, "critical": 6},
        "density_penalty_cap": 60,
        "severity_penalty_cap": 40,
        "rejection_penalty_cap": 20,
        "severity_penalty_multiplier": 10,
    }
    defaults = {
        "sage": {
            "retention_days": 2555,
            "schema_version": "2026.1",
            "policy_version": "2026.1",
            "controls_config": {
                **controls_defaults,
                "density_penalty_cap": 65,
                "severity_penalty_cap": 35,
                "severity_penalty_multiplier": 11,
            },
        },
        "hr": {
            "retention_days": 2555,
            "schema_version": "2026.1",
            "policy_version": "2026.1",
            "controls_config": {
                **controls_defaults,
                "density_penalty_cap": 55,
                "severity_penalty_cap": 45,
                "severity_penalty_multiplier": 9,
            },
        },
        "ops": {"retention_days": 1825, "schema_version": "2026.1", "policy_version": "2026.1", "controls_config": controls_defaults},
        "crm": {"retention_days": 1825, "schema_version": "2026.1", "policy_version": "2026.1", "controls_config": controls_defaults},
    }
    return defaults.get(
        domain,
        {"retention_days": 1825, "schema_version": "2026.1", "policy_version": "2026.1", "controls_config": controls_defaults},
    )


def activate_import_controls_policy(
    *,
    domain: str,
    policy_version: str,
    schema_version: str,
    controls_config: dict,
    approved_by: str,
    approval_reason: str,
    attestation_text: str,
    signature_hash_ref: str,
    notes: str | None = None,
) -> dict | None:
    """Promote a new active controls policy version for a domain.

    Existing active policy for the domain is deactivated before inserting the new one.
    """
    try:
        current = get_import_policy(domain)
        retention_days = int(current.get("retention_days") or 1825)

        (
            db.table(TABLE_DATA_POLICIES)
            .update({"active": False})
            .eq("domain", domain)
            .eq("active", True)
            .execute()
        )

        payload = {
            "domain": domain,
            "policy_version": policy_version,
            "schema_version": schema_version,
            "retention_days": retention_days,
            "controls_config": controls_config,
            "approved_by": approved_by,
            "approval_reason": approval_reason,
            "attestation_text": attestation_text,
            "signature_hash_ref": signature_hash_ref,
            "active": True,
            "notes": notes,
        }
        resp = db.table(TABLE_DATA_POLICIES).insert(payload).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"activate_import_controls_policy failed: {e}")
        return None


def list_import_policy_versions(domain: str, limit: int = 20) -> list[dict]:
    try:
        resp = (
            db.table(TABLE_DATA_POLICIES)
            .select("id,created_at,domain,policy_version,schema_version,retention_days,controls_config,effective_from,active,approved_by,approval_reason,attestation_text,signature_hash_ref,notes")
            .eq("domain", domain)
            .order("effective_from", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logging.error(f"list_import_policy_versions failed: {e}")
        return []


def get_import_policy_version(domain: str, policy_version: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_DATA_POLICIES)
            .select("id,created_at,domain,policy_version,schema_version,retention_days,controls_config,effective_from,active,approved_by,approval_reason,attestation_text,signature_hash_ref,notes")
            .eq("domain", domain)
            .eq("policy_version", policy_version)
            .order("effective_from", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"get_import_policy_version failed: {e}")
        return None


def update_import_job(
    job_id: str | None,
    *,
    status: str,
    counts: dict | None = None,
    lineage: dict | None = None,
    metadata: dict | None = None,
    quality_score: float | None = None,
    error_message: str | None = None,
) -> None:
    """Update import job status and summary diagnostics."""
    if not job_id:
        return
    try:
        payload: dict = {"status": status}
        if counts is not None:
            payload["counts"] = counts
        if lineage is not None:
            payload["lineage"] = lineage
        if metadata is not None:
            payload["metadata"] = metadata
        if quality_score is not None:
            payload["quality_score"] = quality_score
        if error_message:
            payload["error_message"] = error_message[:2000]

        if status in ("succeeded", "failed", "partial_success"):
            import datetime

            payload["finished_at"] = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        db.table(TABLE_IMPORT_JOBS).update(payload).eq("id", job_id).execute()
    except Exception as e:
        logging.error(f"update_import_job failed: {e}")


def insert_import_rejections(job_id: str | None, rejections: list[dict]) -> int:
    """Persist row/header-level rejections for traceability and replay."""
    if not job_id or not rejections:
        return 0
    try:
        payload = []
        for row in rejections:
            payload.append(
                {
                    "job_id": job_id,
                    "dataset": row.get("dataset"),
                    "row_number": row.get("row_number"),
                    "reason": row.get("reason", "validation_error"),
                    "raw_row": row.get("raw_row") or {},
                    "details": row.get("details") or {},
                }
            )
        db.table(TABLE_IMPORT_REJECTIONS).insert(payload).execute()
        return len(payload)
    except Exception as e:
        logging.error(f"insert_import_rejections failed: {e}")
        return 0


def find_import_job_by_idempotency(domain: str, idempotency_key: str) -> dict | None:
    """Find latest job by domain + idempotency key."""
    try:
        resp = (
            db.table(TABLE_IMPORT_JOBS)
            .select("*")
            .eq("domain", domain)
            .eq("idempotency_key", idempotency_key)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"find_import_job_by_idempotency failed: {e}")
        return None


def get_import_job(job_id: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_IMPORT_JOBS)
            .select("*")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"get_import_job failed: {e}")
        return None


def list_import_jobs(limit: int = 50, domain: str | None = None, status: str | None = None) -> list[dict]:
    try:
        q = db.table(TABLE_IMPORT_JOBS).select("*").order("created_at", desc=True).limit(limit)
        if domain:
            q = q.eq("domain", domain)
        if status:
            q = q.eq("status", status)
        resp = q.execute()
        return resp.data or []
    except Exception as e:
        logging.error(f"list_import_jobs failed: {e}")
        return []


def set_promoted_kpi_batch(
    domain: str,
    batch_id: str,
    job_id: str | None = None,
    quality_score: float | None = None,
    rejection_rate: float | None = None,
    reason: str = "quality_gate_passed",
) -> None:
    """Persist the currently promoted batch used for analytics/KPI reads."""
    try:
        payload: dict = {
            "domain": domain,
            "batch_id": batch_id,
            "promoted_reason": reason,
        }
        if job_id:
            payload["job_id"] = job_id
        if quality_score is not None:
            payload["quality_score"] = quality_score
        if rejection_rate is not None:
            payload["rejection_rate"] = rejection_rate

        db.table(TABLE_KPI_PROMOTIONS).upsert(payload, on_conflict="domain").execute()
    except Exception as e:
        logging.error(f"set_promoted_kpi_batch failed: {e}")


def get_promoted_kpi_batch(domain: str) -> dict | None:
    """Return promoted KPI batch row for a domain, if configured."""
    try:
        resp = (
            db.table(TABLE_KPI_PROMOTIONS)
            .select("domain,batch_id,job_id,promoted_at,quality_score,rejection_rate,promoted_reason")
            .eq("domain", domain)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"get_promoted_kpi_batch failed: {e}")
        return None


def get_latest_successful_import_batch(domain: str) -> str | None:
    """Fallback resolver for the latest gate-passed batch from import jobs."""
    try:
        resp = (
            db.table(TABLE_IMPORT_JOBS)
            .select("batch_id")
            .eq("domain", domain)
            .eq("status", "succeeded")
            .order("finished_at", desc=True)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        return rows[0].get("batch_id")
    except Exception as e:
        logging.error(f"get_latest_successful_import_batch failed: {e}")
        return None


def get_snapshot_rows(table: str, batch_id: str, limit: int = 50000) -> list[dict]:
    """Fetch snapshot rows for a specific batch (bounded for safety)."""
    try:
        safe_limit = max(1, min(limit, 200000))
        resp = (
            db.table(table)
            .select("*")
            .eq("batch_id", batch_id)
            .limit(safe_limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logging.error(f"get_snapshot_rows failed for {table}: {e}")
        return []


# ---- Workflow persistence ---------------------------------------------------

def save_intent(intent_id: str, intent_type: str, payload: dict, recommendation: dict) -> None:
    try:
        db.table("placeware_intents").insert({
            "id": intent_id,
            "intent_type": intent_type,
            "payload": payload,
            "recommendation": recommendation,
            "status": "pending",
        }).execute()
    except Exception as e:
        logging.error(f"save_intent failed: {e}")


def save_approval(intent_id: str, approved: bool, approver_note: str | None) -> None:
    try:
        db.table("placeware_approvals").insert({
            "intent_id": intent_id,
            "approved": approved,
            "approver_note": approver_note,
        }).execute()
        # Update intent status
        db.table("placeware_intents").update({"status": "approved" if approved else "rejected"}).eq("id", intent_id).execute()
    except Exception as e:
        logging.error(f"save_approval failed: {e}")


def list_pending_intents(limit: int = 50) -> list[dict]:
    try:
        resp = db.table("placeware_intents").select("id,intent_type,payload,recommendation,status,created_at").eq("status", "pending").order("created_at", desc=True).limit(limit).execute()
        return resp.data or []
    except Exception as e:
        logging.error(f"list_pending_intents failed: {e}")
        return []


# ---- Project Controls persistence ------------------------------------------

def create_project_record(
    name: str,
    description: str | None,
    owner_id: str | None,
    status: str = "active",
    activity_type: str | None = None,
    supplier_name: str | None = None,
    assigned_staff_id: str | None = None,
    workflow_stage: str | None = None,
    po_reference: str | None = None,
    temperature_profile: str | None = None,
    nafdac_sampling_status: str | None = None,
    quality_check_status: str | None = None,
    quality_notes: str | None = None,
) -> dict | None:
    try:
        payload = {
            "name": name,
            "description": description,
            "owner_id": owner_id,
            "status": status,
            "activity_type": activity_type,
            "supplier_name": supplier_name,
            "assigned_staff_id": assigned_staff_id,
            "workflow_stage": workflow_stage,
            "po_reference": po_reference,
            "temperature_profile": temperature_profile,
            "nafdac_sampling_status": nafdac_sampling_status,
            "quality_check_status": quality_check_status,
            "quality_notes": quality_notes,
        }
        resp = db.table(TABLE_PROJECTS).insert(payload).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"create_project_record failed: {e}")
        return None


def list_projects(limit: int = 50, status: str | None = None) -> list[dict]:
    try:
        q = db.table(TABLE_PROJECTS).select("*").order("created_at", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        resp = q.execute()
        return resp.data or []
    except Exception as e:
        logging.error(f"list_projects failed: {e}")
        return []


def get_project(project_id: str) -> dict | None:
    try:
        resp = db.table(TABLE_PROJECTS).select("*").eq("id", project_id).limit(1).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"get_project failed: {e}")
        return None


def update_project_stage(
    project_id: str,
    *,
    workflow_stage: str,
    nafdac_sampling_status: str | None = None,
    quality_check_status: str | None = None,
    quality_notes: str | None = None,
    quality_checked_by: str | None = None,
    quality_checked_at: str | None = None,
) -> dict | None:
    try:
        payload: dict[str, str | None] = {"workflow_stage": workflow_stage}
        if nafdac_sampling_status is not None:
            payload["nafdac_sampling_status"] = nafdac_sampling_status
        if quality_check_status is not None:
            payload["quality_check_status"] = quality_check_status
        if quality_notes is not None:
            payload["quality_notes"] = quality_notes
        if quality_checked_by is not None:
            payload["quality_checked_by"] = quality_checked_by
        if quality_checked_at is not None:
            payload["quality_checked_at"] = quality_checked_at
        resp = db.table(TABLE_PROJECTS).update(payload).eq("id", project_id).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"update_project_stage failed: {e}")
        return None


def create_scope_item(project_id: str, title: str, description: str | None, priority: str, status: str, created_by: str | None) -> dict | None:
    try:
        payload = {
            "project_id": project_id,
            "title": title,
            "description": description,
            "priority": priority,
            "status": status,
            "created_by": created_by,
        }
        resp = db.table(TABLE_SCOPE_ITEMS).insert(payload).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"create_scope_item failed: {e}")
        return None


def list_scope_items(project_id: str, limit: int = 100) -> list[dict]:
    try:
        resp = (
            db.table(TABLE_SCOPE_ITEMS)
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logging.error(f"list_scope_items failed: {e}")
        return []


def get_scope_item(scope_item_id: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_SCOPE_ITEMS)
            .select("*")
            .eq("id", scope_item_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"get_scope_item failed: {e}")
        return None


def update_scope_item_status(scope_item_id: str, status: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_SCOPE_ITEMS)
            .update({"status": status})
            .eq("id", scope_item_id)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"update_scope_item_status failed: {e}")
        return None


def create_cost_item(project_id: str, cost_type: str, amount: float, currency: str, status: str, note: str | None, created_by: str | None) -> dict | None:
    try:
        payload = {
            "project_id": project_id,
            "cost_type": cost_type,
            "amount": amount,
            "currency": currency,
            "status": status,
            "note": note,
            "created_by": created_by,
        }
        resp = db.table(TABLE_COST_ITEMS).insert(payload).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"create_cost_item failed: {e}")
        return None


def list_cost_items(project_id: str, limit: int = 100) -> list[dict]:
    try:
        resp = (
            db.table(TABLE_COST_ITEMS)
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logging.error(f"list_cost_items failed: {e}")
        return []


def get_cost_item(cost_item_id: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_COST_ITEMS)
            .select("*")
            .eq("id", cost_item_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"get_cost_item failed: {e}")
        return None


def update_cost_item_status(cost_item_id: str, status: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_COST_ITEMS)
            .update({"status": status})
            .eq("id", cost_item_id)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"update_cost_item_status failed: {e}")
        return None


def create_risk_item(
    project_id: str,
    title: str,
    description: str | None,
    probability: int,
    impact: int,
    mitigation_plan: str | None,
    owner_id: str | None,
    status: str,
    created_by: str | None,
) -> dict | None:
    try:
        payload = {
            "project_id": project_id,
            "title": title,
            "description": description,
            "probability": probability,
            "impact": impact,
            "mitigation_plan": mitigation_plan,
            "owner_id": owner_id,
            "status": status,
            "created_by": created_by,
        }
        resp = db.table(TABLE_RISK_REGISTER).insert(payload).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"create_risk_item failed: {e}")
        return None


def list_risk_items(project_id: str, limit: int = 100) -> list[dict]:
    try:
        resp = (
            db.table(TABLE_RISK_REGISTER)
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logging.error(f"list_risk_items failed: {e}")
        return []


def get_risk_item(risk_id: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_RISK_REGISTER)
            .select("*")
            .eq("id", risk_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"get_risk_item failed: {e}")
        return None


def update_risk_item_status(risk_id: str, status: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_RISK_REGISTER)
            .update({"status": status})
            .eq("id", risk_id)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"update_risk_item_status failed: {e}")
        return None


def create_change_request(
    project_id: str,
    title: str,
    description: str,
    requested_by: str | None,
    reason_code: str | None,
    impact_scope: str | None,
    impact_cost: float | None,
    impact_schedule_days: int | None,
) -> dict | None:
    try:
        payload = {
            "project_id": project_id,
            "title": title,
            "description": description,
            "requested_by": requested_by,
            "reason_code": reason_code,
            "impact_scope": impact_scope,
            "impact_cost": impact_cost,
            "impact_schedule_days": impact_schedule_days,
            "status": "proposed",
        }
        resp = db.table(TABLE_CHANGE_REQUESTS).insert(payload).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"create_change_request failed: {e}")
        return None


def list_change_requests(project_id: str, limit: int = 100) -> list[dict]:
    try:
        resp = (
            db.table(TABLE_CHANGE_REQUESTS)
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logging.error(f"list_change_requests failed: {e}")
        return []


def get_change_request(change_id: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_CHANGE_REQUESTS)
            .select("*")
            .eq("id", change_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"get_change_request failed: {e}")
        return None


def decide_change_request(
    change_id: str,
    status: str,
    approved_by: str | None,
    approval_note: str | None,
    approval_reason: str | None,
    attestation_text: str | None,
    signature_hash_ref: str | None,
) -> dict | None:
    try:
        payload = {
            "status": status,
            "approved_by": approved_by,
            "approval_note": approval_note,
            "approval_reason": approval_reason,
            "attestation_text": attestation_text,
            "signature_hash_ref": signature_hash_ref,
        }
        if status in ("approved", "rejected"):
            payload["approved_at"] = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        resp = db.table(TABLE_CHANGE_REQUESTS).update(payload).eq("id", change_id).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"decide_change_request failed: {e}")
        return None


def get_controls_rollup(project_id: str | None = None) -> dict:
    try:
        try:
            rpc_resp = db.rpc("placeware_controls_rollup", {"p_project_id": project_id}).execute()
            rpc_data = rpc_resp.data
            if isinstance(rpc_data, dict):
                return rpc_data
            if isinstance(rpc_data, list) and rpc_data:
                first = rpc_data[0]
                if isinstance(first, dict) and "placeware_controls_rollup" in first:
                    value = first.get("placeware_controls_rollup")
                    if isinstance(value, dict):
                        return value
                if isinstance(first, dict):
                    return first
        except Exception as rpc_err:
            logging.warning(f"placeware_controls_rollup RPC unavailable; falling back to app-side aggregation: {rpc_err}")

        def _status_counts(table_name: str) -> dict[str, int]:
            q = db.table(table_name).select("status")
            if project_id:
                q = q.eq("project_id", project_id)
            rows = (q.execute().data or [])
            counts = Counter(str(r.get("status") or "unknown") for r in rows)
            return dict(counts)

        scope_counts = _status_counts(TABLE_SCOPE_ITEMS)
        cost_counts = _status_counts(TABLE_COST_ITEMS)
        risk_counts = _status_counts(TABLE_RISK_REGISTER)
        change_counts = _status_counts(TABLE_CHANGE_REQUESTS)

        rq = db.table(TABLE_RISK_REGISTER).select("status,probability,impact")
        if project_id:
            rq = rq.eq("project_id", project_id)
        risk_rows = rq.execute().data or []

        high_risk_open_count = 0
        for row in risk_rows:
            status = str(row.get("status") or "").strip().lower()
            score = int(row.get("probability") or 0) * int(row.get("impact") or 0)
            if status != "closed" and score >= 15:
                high_risk_open_count += 1

        pending_change_approvals = int(change_counts.get("proposed", 0)) + int(change_counts.get("under_review", 0))

        return {
            "project_id": project_id,
            "scope": {"status_counts": scope_counts, "total": sum(scope_counts.values())},
            "cost": {"status_counts": cost_counts, "total": sum(cost_counts.values())},
            "risk": {
                "status_counts": risk_counts,
                "total": sum(risk_counts.values()),
                "high_risk_open_count": high_risk_open_count,
            },
            "change": {
                "status_counts": change_counts,
                "total": sum(change_counts.values()),
                "pending_approvals": pending_change_approvals,
            },
        }
    except Exception as e:
        logging.error(f"get_controls_rollup failed: {e}")
        return {
            "project_id": project_id,
            "scope": {"status_counts": {}, "total": 0},
            "cost": {"status_counts": {}, "total": 0},
            "risk": {"status_counts": {}, "total": 0, "high_risk_open_count": 0},
            "change": {"status_counts": {}, "total": 0, "pending_approvals": 0},
        }


def list_audit_logs_filtered(
    *,
    limit: int = 200,
    start_at: str | None = None,
    end_at: str | None = None,
    event_class: str | None = None,
    subject_type: str | None = None,
    event_type: str | None = None,
) -> list[dict]:
    try:
        q = db.table(TABLE_AUDIT_LOGS).select("*").order("created_at", desc=True).limit(limit)
        if start_at:
            q = q.gte("created_at", start_at)
        if end_at:
            q = q.lte("created_at", end_at)
        if event_class:
            q = q.eq("event_class", event_class)
        if subject_type:
            q = q.eq("subject_type", subject_type)
        if event_type:
            q = q.eq("event_type", event_type)
        return q.execute().data or []
    except Exception as e:
        logging.error(f"list_audit_logs_filtered failed: {e}")
        return []


# ---- Duplicate import detection -------------------------------------------

def is_duplicate_import(import_hash: str, within_minutes: int = 1440) -> bool:
    """Check audit logs for a recent import with the same hash.

    Returns True if a duplicate is found within the given window.
    """
    try:
        import datetime
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=within_minutes)
        cutoff_iso = cutoff.replace(microsecond=0).isoformat() + "Z"
        resp = (
            db
            .table(TABLE_AUDIT_LOGS)
            .select("details,created_at")
            .eq("event_type", "sage_import_validated")
            .gte("created_at", cutoff_iso)
            .execute()
        )
        for row in (resp.data or []):
            det = row.get("details") or {}
            if det.get("hash") == import_hash:
                return True
        return False
    except Exception as e:
        logging.error(f"is_duplicate_import failed: {e}")
        return False


# ---- Chat history ----------------------------------------------------------

def save_chat_history(user_id: str | None, question: str, answer: str, sources: list[dict]) -> None:
    from .constants import TABLE_CHAT_HISTORY
    try:
        db.table(TABLE_CHAT_HISTORY).insert({
            "user_id": user_id,
            "question": question,
            "answer": answer,
            "sources": sources,
        }).execute()
    except Exception as e:
        logging.error(f"save_chat_history failed: {e}")


def get_chat_history(user_id: str, limit: int = 30) -> list[dict]:
    from .constants import TABLE_CHAT_HISTORY
    safe_limit = max(1, min(limit, 200))
    try:
        resp = (
            db.table(TABLE_CHAT_HISTORY)
            .select("id,created_at,user_id,question,answer,sources")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(safe_limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logging.error(f"get_chat_history failed: {e}")
        return []


def get_audit_logs(limit: int = 50) -> list[dict]:
    """Fetch recent audit logs for history display."""
    try:
        resp = db.table(TABLE_AUDIT_LOGS)\
            .select("*")\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()
        return resp.data or []
    except Exception as e:
        logging.error(f"get_audit_logs failed: {e}")
        return []


# ---- Auth persistence ------------------------------------------------------

def get_user_by_email(email: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_USERS)
            .select("id,email,hashed_password,roles,is_active")
            .eq("email", email.lower())
            .limit(1)
            .execute()
        )
        data = resp.data or []
        return data[0] if data else None
    except Exception as e:
        logging.error(f"get_user_by_email failed: {e}")
        return None


def get_user_by_id(user_id: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_USERS)
            .select("id,email,roles,is_active")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        return data[0] if data else None
    except Exception as e:
        logging.error(f"get_user_by_id failed: {e}")
        return None


def insert_refresh_token(
    user_id: str,
    token_hash: str,
    expires_at: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
    replaced_by: str | None = None,
) -> str | None:
    try:
        payload = {
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "user_agent": user_agent,
            "ip_address": ip_address,
            "replaced_by": replaced_by,
        }
        resp = db.table(TABLE_REFRESH_TOKENS).insert(payload).execute()
        data = resp.data or []
        return data[0]["id"] if data else None
    except Exception as e:
        logging.error(f"insert_refresh_token failed: {e}")
        return None


def get_refresh_token_record(token_hash: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_REFRESH_TOKENS)
            .select("id,user_id,token_hash,expires_at,revoked_at")
            .eq("token_hash", token_hash)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        return data[0] if data else None
    except Exception as e:
        logging.error(f"get_refresh_token_record failed: {e}")
        raise AuthStoreUnavailableError("refresh token store unavailable") from e


def revoke_refresh_token(token_id: str, replaced_by: str | None = None) -> None:
    try:
        import datetime as dt
        now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        payload = {"revoked_at": now}
        if replaced_by:
            payload["replaced_by"] = replaced_by
        db.table(TABLE_REFRESH_TOKENS).update(payload).eq("id", token_id).execute()
    except Exception as e:
        logging.error(f"revoke_refresh_token failed: {e}")


def list_users(limit: int = 50) -> list[dict]:
    try:
        resp = (
            db.table(TABLE_USERS)
            .select("id,email,roles,is_active,created_at,updated_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logging.error(f"list_users failed: {e}")
        return []


def create_user(email: str, hashed_password: str, roles: list[str]) -> str | None:
    try:
        payload = {
            "email": email.lower(),
            "hashed_password": hashed_password,
            "roles": roles,
            "is_active": True,
        }
        resp = db.table(TABLE_USERS).insert(payload).execute()
        data = resp.data or []
        return data[0]["id"] if data else None
    except Exception as e:
        logging.error(f"create_user failed: {e}")
        return None


def update_user_password(user_id: str, hashed_password: str) -> bool:
    try:
        import datetime as dt
        now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        db.table(TABLE_USERS).update({
            "hashed_password": hashed_password,
            "updated_at": now
        }).eq("id", user_id).execute()
        return True
    except Exception as e:
        logging.error(f"update_user_password failed: {e}")
        return False


def toggle_user_active(user_id: str, is_active: bool) -> bool:
    try:
        import datetime as dt
        now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        db.table(TABLE_USERS).update({
            "is_active": is_active,
            "updated_at": now
        }).eq("id", user_id).execute()
        return True
    except Exception as e:
        logging.error(f"toggle_user_active failed: {e}")
        return False


def create_procurement_shipment(payload: dict) -> dict | None:
    try:
        resp = db.table(TABLE_PROCUREMENT_SHIPMENTS).insert(payload).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"create_procurement_shipment failed: {e}")
        return None


def list_procurement_shipments(
    *,
    limit: int = 100,
    status: str | None = None,
    supplier_name: str | None = None,
) -> list[dict]:
    try:
        safe_limit = max(1, min(limit, 500))
        q = (
            db.table(TABLE_PROCUREMENT_SHIPMENTS)
            .select("*")
            .order("created_at", desc=True)
            .limit(safe_limit)
        )
        if status:
            q = q.eq("status", status)
        if supplier_name:
            q = q.ilike("supplier_name", f"%{supplier_name.strip()}%")
        resp = q.execute()
        return resp.data or []
    except Exception as e:
        logging.error(f"list_procurement_shipments failed: {e}")
        return []


def get_procurement_shipment(shipment_id: str) -> dict | None:
    try:
        resp = (
            db.table(TABLE_PROCUREMENT_SHIPMENTS)
            .select("*")
            .eq("id", shipment_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"get_procurement_shipment failed: {e}")
        return None


def update_procurement_shipment(shipment_id: str, updates: dict) -> dict | None:
    try:
        resp = (
            db.table(TABLE_PROCUREMENT_SHIPMENTS)
            .update(updates)
            .eq("id", shipment_id)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"update_procurement_shipment failed: {e}")
        return None


def create_procurement_shipment_event(payload: dict) -> dict | None:
    try:
        resp = db.table(TABLE_PROCUREMENT_SHIPMENT_EVENTS).insert(payload).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.error(f"create_procurement_shipment_event failed: {e}")
        return None


def list_procurement_events_feed(
    *,
    limit: int = 100,
    since_event_id: int | None = None,
) -> list[dict]:
    try:
        safe_limit = max(1, min(limit, 500))
        q = db.table(TABLE_PROCUREMENT_SHIPMENT_EVENTS).select("*")
        if since_event_id is not None:
            q = q.gt("id", int(since_event_id)).order("id", desc=False).limit(safe_limit)
        else:
            q = q.order("id", desc=True).limit(safe_limit)
        rows = q.execute().data or []
        if since_event_id is None:
            rows.reverse()
        return rows
    except Exception as e:
        logging.error(f"list_procurement_events_feed failed: {e}")
        return []


def send_procurement_escalation_email(
    *,
    shipment: dict,
    reason: str,
    actor_id: str | None,
    notify_regulatory: bool,
    notify_executive_dashboard: bool,
) -> dict[str, object]:
    try:
        recipients_out: list[str] = []
        if notify_regulatory:
            recipient = (
                recipients.get("regulatory")
                or recipients.get("compliance")
                or recipients.get("operations")
                or recipients.get("ops")
            )
            if recipient:
                recipients_out.append(str(recipient).strip())

        if notify_executive_dashboard:
            recipient = (
                recipients.get("executive")
                or recipients.get("management")
                or recipients.get("operations")
                or recipients.get("ops")
            )
            if recipient:
                recipients_out.append(str(recipient).strip())

        if not recipients_out:
            fallback = recipients.get("operations") or recipients.get("marketing") or EMAIL_FROM
            if fallback:
                recipients_out.append(str(fallback).strip())

        recipients_out = sorted({email for email in recipients_out if email})

        if not (EMAIL_FROM and EMAIL_PASS and recipients_out):
            return {
                "sent": False,
                "recipients": recipients_out,
                "reason": "missing_email_credentials_or_recipients",
            }

        shipment_ref = str(shipment.get("shipment_ref") or "unknown")
        supplier_name = str(shipment.get("supplier_name") or "unknown")
        status = str(shipment.get("status") or "unknown")
        subject = f"Procurement Escalation: {shipment_ref}"
        body = (
            f"A procurement shipment has been escalated in {BOT_NAME}.\n"
            f"Shipment Ref: {shipment_ref}\n"
            f"Supplier: {supplier_name}\n"
            f"Current Status: {status}\n"
            f"Reason: {reason}\n"
            f"Actor: {actor_id or 'system'}\n"
        )

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = ", ".join(recipients_out)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASS)
            server.send_message(msg)

        return {
            "sent": True,
            "recipients": recipients_out,
        }
    except Exception as e:
        logging.error(f"send_procurement_escalation_email failed: {e}")
        return {
            "sent": False,
            "recipients": [],
            "reason": "delivery_error",
        }


def list_procurement_shipment_events(shipment_id: str, limit: int = 100) -> list[dict]:
    try:
        safe_limit = max(1, min(limit, 500))
        resp = (
            db.table(TABLE_PROCUREMENT_SHIPMENT_EVENTS)
            .select("*")
            .eq("shipment_id", shipment_id)
            .order("created_at", desc=True)
            .limit(safe_limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logging.error(f"list_procurement_shipment_events failed: {e}")
        return []
