"""Phone / desktop notifications through Web Push (client, 6 Nov 2026).

A device turns notifications on from ACE (bell > "Notify me on this device"); its push subscription is kept in
web_push_subscriptions. Every in-app notification at level 'action' or 'critical' (an invoice waiting for
approval, an escalation...) is then also sent to that person's devices, so Finance and the CFO/CEO hear about
an invoice even when ACE is not open. Sending runs on a background thread and never holds up the request
that raised the notification.

Needs HTTPS with a trusted certificate (browsers only allow push on secure sites) and, on an iPhone, iOS 16.4+
with ACE added to the Home Screen.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
from typing import Any, Dict, Iterable, Optional

from src.fin.db import ex, q, q1, tx

log = logging.getLogger(__name__)

# What reaches a phone: things someone has to act on, not every "for your information" item.
PUSH_LEVELS = {"action", "critical"}
_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@placewareaiapp.online")
_key_lock = threading.Lock()
_keys: Optional[Dict[str, Any]] = None


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _load_keys() -> Dict[str, Any]:
    """The VAPID key pair: from VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY if set, else the one in the database
    (made on first use)."""
    global _keys
    if _keys:
        return _keys
    with _key_lock:
        if _keys:
            return _keys
        from py_vapid import Vapid
        from cryptography.hazmat.primitives import serialization
        priv, pub = os.getenv("VAPID_PRIVATE_KEY"), os.getenv("VAPID_PUBLIC_KEY")
        if not (priv and pub):
            with tx() as conn:
                row = q1(conn, "SELECT private_der_b64, public_key_b64 FROM web_push_keys WHERE id=1")
                if not row:
                    v = Vapid()
                    v.generate_keys()
                    der = v.private_key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                      serialization.NoEncryption())
                    raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
                    # two workers racing: the first insert wins and both read it back
                    ex(conn, """INSERT INTO web_push_keys (id, private_der_b64, public_key_b64) VALUES (1, %s, %s)
                                ON CONFLICT (id) DO NOTHING""", (_b64(der), _b64(raw)))
                    row = q1(conn, "SELECT private_der_b64, public_key_b64 FROM web_push_keys WHERE id=1")
            priv, pub = row["private_der_b64"], row["public_key_b64"]
        _keys = {"vapid": Vapid.from_der(priv.encode()), "public": pub}
        return _keys


def public_key() -> str:
    return _load_keys()["public"]


def subscribe(user_id: str, sub: Dict[str, Any], user_agent: Optional[str]) -> None:
    keys = sub.get("keys") or {}
    if not (sub.get("endpoint") and keys.get("p256dh") and keys.get("auth")):
        raise ValueError("Not a push subscription")
    with tx() as conn:
        # a device that changes hands (another login on the same phone) now belongs to the new login
        ex(conn, """INSERT INTO web_push_subscriptions (user_id, endpoint, p256dh, auth, user_agent)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (endpoint) DO UPDATE SET user_id=EXCLUDED.user_id, p256dh=EXCLUDED.p256dh, auth=EXCLUDED.auth,
                        user_agent=EXCLUDED.user_agent, failures=0""",
           (user_id, sub["endpoint"], keys["p256dh"], keys["auth"], (user_agent or "")[:300]))


def unsubscribe(user_id: str, endpoint: Optional[str]) -> int:
    with tx() as conn:
        if endpoint:
            return ex(conn, "DELETE FROM web_push_subscriptions WHERE user_id=%s AND endpoint=%s", (user_id, endpoint)) or 0
        return ex(conn, "DELETE FROM web_push_subscriptions WHERE user_id=%s", (user_id,)) or 0


def devices(user_id: str) -> list:
    with tx() as conn:
        return q(conn, """SELECT id, user_agent, created_at, last_sent_at FROM web_push_subscriptions
                          WHERE user_id=%s ORDER BY created_at DESC""", (user_id,))


def _send_now(user_ids: list, payload: Dict[str, Any]) -> Dict[str, int]:
    from pywebpush import WebPushException, webpush
    out = {"sent": 0, "failed": 0, "removed": 0}
    try:
        vapid = _load_keys()["vapid"]
        with tx() as conn:
            subs = q(conn, "SELECT id, endpoint, p256dh, auth FROM web_push_subscriptions WHERE user_id::text = ANY(%s)",
                     ([str(u) for u in user_ids],))
    except Exception as exc:
        log.warning("web push unavailable: %s", exc)
        return out
    data = json.dumps(payload)
    for s in subs:
        gone = False
        try:
            webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, data,
                    vapid_private_key=vapid, vapid_claims={"sub": _SUBJECT}, ttl=24 * 3600, timeout=10)
            ok = True
        except WebPushException as exc:
            ok = False
            status = getattr(getattr(exc, "response", None), "status_code", None)
            gone = status in (404, 410)  # the device turned notifications off or the app was removed
            log.info("web push to subscription %s failed (%s): %s", s["id"], status, exc)
        except Exception as exc:
            ok = False
            log.info("web push to subscription %s failed: %s", s["id"], exc)
        try:
            with tx() as conn:
                if gone:
                    ex(conn, "DELETE FROM web_push_subscriptions WHERE id=%s", (s["id"],))
                    out["removed"] += 1
                elif ok:
                    ex(conn, "UPDATE web_push_subscriptions SET last_sent_at=now(), failures=0 WHERE id=%s", (s["id"],))
                else:
                    # a device that keeps failing (switched off for months) is dropped after 20 tries
                    ex(conn, """UPDATE web_push_subscriptions SET failures=failures+1 WHERE id=%s;
                                DELETE FROM web_push_subscriptions WHERE id=%s AND failures >= 20""", (s["id"], s["id"]))
        except Exception:
            pass
        out["sent" if ok else "failed"] += 1
    return out


def send(user_ids: Iterable[str], title: str, body: Optional[str] = None, path: Optional[str] = None,
         tag: Optional[str] = None, wait: bool = False) -> Optional[Dict[str, int]]:
    """Notify these people's devices. Background by default (never delays the caller)."""
    ids = sorted({str(u) for u in user_ids if u})
    if not ids:
        return {"sent": 0, "failed": 0, "removed": 0} if wait else None
    payload = {"title": title[:120], "body": (body or "")[:300], "url": f"#{path}" if path and path.startswith("/") else (path or "#/"),
               "tag": tag}
    if wait:
        return _send_now(ids, payload)
    threading.Thread(target=_send_now, args=(ids, payload), name="web-push", daemon=True).start()
    return None
