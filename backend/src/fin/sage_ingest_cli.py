"""Load folders of Sage exports into ACE Books' history (display + lineage only).

    python -m src.fin.sage_ingest_cli <folder> [<folder> ...] [--dry-run]

Folders are loaded oldest first: a later folder replaces what an earlier one held for the dates
it covers (e.g. the first export ran to 30 Jun, the next from 1 Jun to date - June comes from
the newer file). --dry-run loads everything inside one transaction and rolls it back.
"""
from __future__ import annotations

import json
import sys
import time

from src.fin.context import system_context
from src.fin.db import tx
from src.fin import sage_ledger


class _DryRun(Exception):
    pass


def main(argv):
    dry = "--dry-run" in argv
    folders = [a for a in argv if not a.startswith("--")]
    if not folders:
        print(__doc__)
        return 2
    t0 = time.time()
    try:
        with tx() as conn:
            ctx = system_context(conn, actor="sage-history-load")
            res = sage_ledger.ingest_folders(conn, ctx, folders)
            for r in res:
                print(json.dumps(r, default=str)[:600])
            print("coverage:", json.dumps(sage_ledger.coverage(conn, ctx.entity_id), default=str))
            if dry:
                raise _DryRun()
    except _DryRun:
        print("DRY RUN - rolled back")
    print(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
