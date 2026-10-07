#!/usr/bin/env python3
"""NeuroLayer licence tool - runs ONLY on the NeuroLayer administrator's machine.

    keygen   create your private signing key (passphrase-protected) - once, ever
    issue    sign a licence for a client -> a system.dat file to drop on their server
    inspect  verify a system.dat and show what it grants

Examples (from the repo root):
    python tools/licensing/neurolayer_license.py keygen --install
    python tools/licensing/neurolayer_license.py issue --client "Placeware Ltd" --license-id PW-001 --months 1
    python tools/licensing/neurolayer_license.py inspect backend/.license/system.dat

Passphrase: prompted for; set NEUROLAYER_KEY_PASSPHRASE to skip the prompt (automation only).
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from src.licensing.license_format import (  # noqa: E402
    LOCK_MODES, LicenseFormatError, extract_token, license_window, load_public_key, public_key_b64,
    sign_license, verify_license,
)

KEY_HOME = Path(os.getenv("NEUROLAYER_KEY_HOME") or Path.home() / ".neurolayer" / "licensing")
PRIVATE_KEY_FILE = "neurolayer_license_signing_key.pem"
PUBLIC_KEY_FILE = "neurolayer_license_public_key.txt"
PUBLIC_KEY_PY = REPO_ROOT / "backend" / "src" / "licensing" / "public_key.py"
LOCAL_LICENSE = REPO_ROOT / "backend" / ".license" / "system.dat"


def _passphrase(confirm: bool) -> bytes:
    env = os.getenv("NEUROLAYER_KEY_PASSPHRASE")
    if env:
        return env.encode()
    pw = getpass.getpass("Signing-key passphrase: ")
    if confirm:
        if len(pw) < 12:
            sys.exit("Use at least 12 characters - this passphrase is the only thing protecting your key.")
        if pw != getpass.getpass("Repeat passphrase: "):
            sys.exit("Passphrases did not match.")
    return pw.encode()


def _installed_public_key() -> str:
    m = re.search(r'NEUROLAYER_LICENSE_PUBLIC_KEY\s*=\s*"([^"]*)"', PUBLIC_KEY_PY.read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def _install_public_key(pub: str) -> None:
    text = PUBLIC_KEY_PY.read_text(encoding="utf-8")
    PUBLIC_KEY_PY.write_text(
        re.sub(r'NEUROLAYER_LICENSE_PUBLIC_KEY\s*=\s*"[^"]*"', f'NEUROLAYER_LICENSE_PUBLIC_KEY = "{pub}"', text),
        encoding="utf-8",
    )


def cmd_keygen(args) -> None:
    out = Path(args.out).expanduser().resolve()
    if out == REPO_ROOT or REPO_ROOT in out.parents:
        sys.exit(f"Refusing to write the private key inside the repository ({REPO_ROOT}). Pick a folder outside it.")
    key_path = out / PRIVATE_KEY_FILE
    if key_path.exists() and not args.force:
        sys.exit(f"{key_path} already exists. Every licence ever issued depends on it - use --force only if "
                 "you really mean to replace it (all existing licences stop verifying after the next build).")
    pw = _passphrase(confirm=True)
    key = Ed25519PrivateKey.generate()
    out.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(pw)))
    pub = public_key_b64(key)
    (out / PUBLIC_KEY_FILE).write_text(pub + "\n", encoding="ascii")
    print(f"Private key (keep secret, back it up): {key_path}")
    print(f"Public key: {pub}")
    if args.install:
        _install_public_key(pub)
        print(f"Installed public key into {PUBLIC_KEY_PY.relative_to(REPO_ROOT)} - rebuild the backend image once.")
    else:
        print(f"Run again with --install, or paste the public key into {PUBLIC_KEY_PY.relative_to(REPO_ROOT)}.")


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    if not path.exists():
        sys.exit(f"No signing key at {path}. Run 'keygen' first, or pass --key.")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=_passphrase(confirm=False))
    except (ValueError, TypeError):
        sys.exit("Wrong passphrase (or the key file is damaged).")
    if not isinstance(key, Ed25519PrivateKey):
        sys.exit("That key file is not an Ed25519 licence signing key.")
    return key


def _describe(payload: dict) -> str:
    start, expiry, grace_end = license_window(payload)
    return "\n".join([
        f"  Licence ID : {payload['license_id']}",
        f"  Issued to  : {payload['issued_to']}",
        f"  Start      : {start:%d %b %Y}",
        f"  Duration   : {payload['duration_months']} month(s)",
        f"  Expires    : {expiry:%d %b %Y}",
        f"  Grace until: {grace_end:%d %b %Y} ({payload.get('grace_period_days', 7)} days)",
        f"  Lock mode  : {payload.get('lock_mode', 'full')}",
        f"  Issued at  : {payload['issued_at']}",
    ])


def cmd_issue(args) -> None:
    key = _load_private_key(Path(args.key).expanduser())
    start = dt.date.fromisoformat(args.start) if args.start else dt.date.today()
    payload = {
        "v": 1,
        "license_id": args.license_id,
        "issued_to": args.client,
        "start_date": start.isoformat(),
        "duration_months": args.months,
        "grace_period_days": args.grace,
        "lock_mode": args.lock_mode,
        "modules": ["all"],
        "support_contact": args.support,
        "issued_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    token = sign_license(payload, key)
    verify_license(token, key.public_key())  # sanity: round-trips

    if args.install_local:
        out = LOCAL_LICENSE
    elif args.out:
        out = Path(args.out).expanduser()
    else:
        out = KEY_HOME / "issued" / f"{args.license_id}_{start.isoformat()}" / "system.dat"
    _, expiry, _ = license_window(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"# Placeware licence - {args.client} ({args.license_id})\n"
        f"# {start:%d %b %Y} -> {expiry:%d %b %Y}. These comment lines are informational only;\n"
        f"# the signed line below is what the server checks. Editing it invalidates the licence.\n"
        f"{token}\n",
        encoding="utf-8",
    )
    print("Licence issued:\n" + _describe(payload))
    print(f"\nFile: {out}")
    if _installed_public_key() != public_key_b64(key):
        print("\nWARNING: this key does not match backend/src/licensing/public_key.py - "
              "servers built from this repo will reject the licence.")


def cmd_inspect(args) -> None:
    path = Path(args.file).expanduser()
    pub = _installed_public_key()
    if not pub:
        sys.exit("backend/src/licensing/public_key.py has no public key yet - run 'keygen --install' first.")
    try:
        payload = verify_license(extract_token(path.read_text(encoding="utf-8")), load_public_key(pub))
    except (OSError, LicenseFormatError) as exc:
        sys.exit(f"INVALID: {exc}")
    _, expiry, grace_end = license_window(payload)
    today = dt.date.today()
    state = "VALID" if today < expiry else "IN GRACE" if today < grace_end else "EXPIRED"
    print(f"Signature OK - {state} today ({today:%d %b %Y})\n" + _describe(payload))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("keygen", help="create the private signing key (once)")
    k.add_argument("--out", default=str(KEY_HOME), help=f"folder for the key (default {KEY_HOME})")
    k.add_argument("--install", action="store_true", help="write the public key into the backend source")
    k.add_argument("--force", action="store_true", help="overwrite an existing key")
    k.set_defaults(fn=cmd_keygen)

    i = sub.add_parser("issue", help="sign a licence")
    i.add_argument("--client", required=True, help='licensee name, e.g. "Placeware Ltd"')
    i.add_argument("--license-id", required=True, help="your reference, e.g. PW-001")
    i.add_argument("--start", help="YYYY-MM-DD (default today)")
    i.add_argument("--months", type=int, default=1, help="duration in months (default 1)")
    i.add_argument("--grace", type=int, default=7, help="grace days after expiry (default 7)")
    i.add_argument("--lock-mode", choices=LOCK_MODES, default="full",
                   help="after grace: 'full' blocks everything, 'read_only' still allows viewing")
    i.add_argument("--support", default="NeuroLayer Support", help="contact shown on the locked screen")
    i.add_argument("--key", default=str(KEY_HOME / PRIVATE_KEY_FILE), help="private key file")
    dest = i.add_mutually_exclusive_group()
    dest.add_argument("--out", help="where to write system.dat")
    dest.add_argument("--install-local", action="store_true", help="write to backend/.license/system.dat (dev box)")
    i.set_defaults(fn=cmd_issue)

    s = sub.add_parser("inspect", help="verify a licence file")
    s.add_argument("file", help="path to system.dat")
    s.set_defaults(fn=cmd_inspect)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
