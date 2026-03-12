import os
import json
from .engine import LEDGER_PATH


def push_event_to_file(event: dict) -> None:
    """Append event JSON as a single line to the workflow ledger file used by the local engine."""
    parent = os.path.dirname(LEDGER_PATH)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    try:
        with open(LEDGER_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
    except Exception:
        # best-effort; don't raise to avoid failing API call
        pass
