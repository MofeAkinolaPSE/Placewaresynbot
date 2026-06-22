"""ingest.py — Sage 50 2013 (Peachtree) data ingestion pipeline.

Reads directly from the Pervasive PSQL database folder (no ODBC, no Pervasive
installation required) and loads all business data into Synbot.

Compatible with Python 3.8+ (Windows 7 / py38 embeddable) and Python 3.12+
(Docker python:3.12-slim).

Usage examples
--------------
  # Step 1: Discover tables + companies (NO DB WRITES — safe first run)
  python ingest.py --source "D:\\Sage Data 1" --step discover

  # Step 2: Dry run for one company (shows mapped rows, no writes)
  python ingest.py --source "D:\\Sage Data 1" --company plaphaen --dry-run

  # Step 3: Full load via backend API
  python ingest.py --source "D:\\Sage Data 1" --company plaphaen \\
      --upload http://localhost --token eyJhbGci...

  # Step 3 (alternative): Direct PostgreSQL write
  python ingest.py --source "D:\\Sage Data 1" --company plaphaen \\
      --db-url "postgresql://postgres:admin1234@localhost:5432/synbot_demo"

  # Load a single entity only
  python ingest.py --source "D:\\Sage Data 1" --company plaphaen \\
      --entity customers --upload http://localhost --token eyJ...

  # Docker version (run from project root — two mounts needed):
  # docker run --rm --network deploy_royan_net \\
  #   -v "%cd%\\data-assimilation":/dal \\
  #   -v "D:\\Sage Data 1":/sage \\
  #   -e DATABASE_URL=postgresql://postgres:admin1234@db:5432/synbot_demo \\
  #   python:3.12-slim \\
  #   bash -c "cd /dal && pip install -r requirements.txt -q && \\
  #            python ingest.py --source /sage --company plaphaen --entity all"
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

# ── stdlib only imports above; third-party checked at runtime ──────────────

# Ensure stdout handles all Unicode on Windows (CP1252 console would crash otherwise)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.WARNING,   # default quiet; -v raises to INFO/DEBUG
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("ingest")


# ---------------------------------------------------------------------------
# Phase 1 — Detect source format
# ---------------------------------------------------------------------------

def phase_detect(source: str) -> tuple:
    """Return (mode, resolved_root, tempdir_to_cleanup)."""
    from sage50 import detector
    return detector.detect(source)


# ---------------------------------------------------------------------------
# Phase 2 — Parse schema from DDF files (btrieve mode)
# ---------------------------------------------------------------------------

def phase_parse_schema(sage_root: str, company: Optional[str]) -> dict:
    from sage50 import ddf_parser
    schema = ddf_parser.parse(sage_root, company_subfolder=company)
    return schema


# ---------------------------------------------------------------------------
# Phase 3 — Extract rows per entity
# ---------------------------------------------------------------------------

def phase_extract(
    sage_root: str,
    schema: dict,
    company: Optional[str],
    entity_names: List[str],
    dry_run: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return {entity_name: [mapped_row, ...]} for each requested entity."""
    from sage50 import btrieve_reader, detector as det
    import field_maps

    datasets: Dict[str, List[Dict]] = {}

    for entity_name in entity_names:
        cfg = field_maps.ENTITY_MAPS.get(entity_name)
        if not cfg:
            log.warning(f"  Unknown entity '{entity_name}' — skipped")
            continue

        rows = _extract_entity(
            entity_name=entity_name,
            cfg=cfg,
            schema=schema,
            sage_root=sage_root,
            company=company,
            dry_run=dry_run,
        )
        datasets[entity_name] = rows

    return datasets


def _extract_entity(
    entity_name: str,
    cfg: dict,
    schema: dict,
    sage_root: str,
    company: Optional[str],
    dry_run: bool,
) -> List[Dict]:
    from sage50 import btrieve_reader, hard_reader
    import field_maps

    # ── Hard-coded reader (primary path) ───────────────────────────────────
    # FIELD.DDF parsing is unreliable for Pervasive PSQL v10 files.
    # For the essential entities we have confirmed binary layouts.
    hard_rows = hard_reader.read_entity(
        entity_name, sage_root, company,
        max_rows=10 if dry_run else None,
    )
    if hard_rows is not None:
        available_cols = hard_reader.field_names(entity_name)
        rows_out: List[Dict] = []
        for raw in hard_rows:
            mapped = field_maps.map_row(raw, entity_name, available_cols)
            if mapped is not None:
                rows_out.append(mapped)
        log.info(
            f"  [{entity_name}] hard_reader: dat={cfg['sage_tables'][0]}.DAT "
            f"rows={len(rows_out)}"
        )
        return rows_out

    # ── DDF-schema reader (fallback for entities without hard schemas) ──────
    table_schema = None
    matched_table = None
    for candidate_table in cfg["sage_tables"]:
        t = schema.get(candidate_table.upper())
        if t is not None:
            table_schema = t
            matched_table = candidate_table
            break

    if table_schema is None:
        log.info(f"  [{entity_name}] No matching table found in schema — skipped")
        return []

    dat_path = table_schema.dat_path
    if not os.path.exists(dat_path):
        log.info(f"  [{entity_name}] DAT file not found: {dat_path} — skipped")
        return []

    available_cols = [f.name for f in table_schema.fields]
    if not available_cols:
        log.info(f"  [{entity_name}] No field definitions in schema — skipped")
        return []

    field_defs = [f.as_dict() for f in table_schema.fields]
    physical_slot = table_schema.physical_slot_len

    page_size, _ = btrieve_reader.read_header(dat_path)

    rows_out = []
    errors = 0

    try:
        for slot in btrieve_reader.iter_records(dat_path, physical_slot, page_size):
            raw = btrieve_reader.record_to_dict(slot, field_defs)
            mapped = field_maps.map_row(raw, entity_name, available_cols)
            if mapped is None:
                continue
            rows_out.append(mapped)
            if dry_run and len(rows_out) >= 10:
                break
    except Exception as exc:
        log.warning(f"  [{entity_name}] Read error: {exc}")

    log.info(f"  [{entity_name}] table={matched_table} dat={os.path.basename(dat_path)} "
             f"rows={len(rows_out)} errors={errors}")
    return rows_out


# ---------------------------------------------------------------------------
# Phase 4 — Load
# ---------------------------------------------------------------------------

def phase_load_api(datasets: Dict[str, List], url: str, token: str) -> dict:
    from sage50.loader import upload_to_backend
    return upload_to_backend(datasets, url, token)


def phase_load_db(datasets: Dict[str, List], db_url: str) -> dict:
    from sage50.loader import upload_direct_db
    import field_maps
    return upload_direct_db(datasets, db_url, field_maps.TARGET_TABLES)


# ---------------------------------------------------------------------------
# Discover mode
# ---------------------------------------------------------------------------

def run_discover(source: str) -> None:
    from sage50 import detector, ddf_parser

    print(f"\n[DISCOVER] Source: {source}")

    mode, sage_root, tmpdir = detector.detect(source)
    print(f"  Format detected   : {mode.upper()}")

    if mode == "btrieve":
        print(f"  Sage root         : {sage_root}")

        # List companies
        companies = detector.list_companies(sage_root)
        if companies:
            print(f"\n  Companies found ({len(companies)}):")
            for folder, label in companies.items():
                print(f"    {folder:<16}  {label}")
        else:
            print("  No company subfolders detected (run from Sage data root?)")

        # Parse each company's DDF independently (company-level DDF is much more complete)
        print()
        for folder in companies:
            print(f"  Parsing schema for [{folder}] ...")
            try:
                schema = ddf_parser.parse(sage_root, company_subfolder=folder)
            except Exception as exc:
                print(f"    ERROR: {exc}")
                continue

            tables_with_fields = [(n, ts) for n, ts in schema.items() if ts.fields]
            tables_no_fields   = [(n, ts) for n, ts in schema.items() if not ts.fields]

            print(f"    {len(schema)} tables  "
                  f"({len(tables_with_fields)} with field defs, "
                  f"{len(tables_no_fields)} metadata-only)")

            # Show first 15 tables that have field definitions
            for t, ts in sorted(tables_with_fields)[:15]:
                dat_name = os.path.basename(ts.dat_path)
                exists = "OK" if os.path.exists(ts.dat_path) else "MISSING"
                print(f"      {t:<28} {len(ts.fields):>3} fields  "
                      f"rec={ts.logical_rec_len}b  {dat_name}  [{exists}]")
            if len(tables_with_fields) > 15:
                print(f"      ... and {len(tables_with_fields) - 15} more tables")
            print()

    elif mode == "csv":
        import glob
        csvs = sorted(glob.glob(os.path.join(sage_root, "*.csv")) +
                      glob.glob(os.path.join(sage_root, "*.CSV")))
        print(f"  CSV files found ({len(csvs)}):")
        for c in csvs:
            size_kb = os.path.getsize(c) // 1024
            print(f"    {os.path.basename(c):<40} {size_kb:>6} KB")
    else:
        print("  Could not detect format. Check that the path points to the "
              "'Sage Data 1' folder containing FILE.DDF and FIELD.DDF.")

    if tmpdir:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CSV fallback mode
# ---------------------------------------------------------------------------

def run_csv_mode(
    sage_root: str,
    entity_names: List[str],
    dry_run: bool,
) -> Dict[str, List[Dict]]:
    """Read CSV files from a folder using existing field_maps candidate lists."""
    import csv
    import glob
    import field_maps

    datasets: Dict[str, List[Dict]] = {}

    # Build filename → file_type alias map (same as backend router)
    _ALIASES = {
        "customers": "customers", "customer": "customers",
        "vendors": "vendors", "vendor": "vendors", "suppliers": "vendors",
        "chart_of_accounts": "chart_of_accounts", "coa": "chart_of_accounts",
        "items": "items", "item": "items",
        "stock_on_hand": "stock_on_hand", "stock": "stock_on_hand", "inventory": "stock_on_hand",
        "sales_invoices": "sales_invoices", "invoices": "sales_invoices", "invoice": "sales_invoices",
        "sales_invoice_lines": "sales_invoice_lines", "invoice_lines": "sales_invoice_lines",
        "purchase_orders": "purchase_orders", "po": "purchase_orders",
        "inventory_transactions": "inventory_transactions",
        "gl_journal_entries": "gl_journal_entries", "gl": "gl_journal_entries",
        "staff": "staff", "employees": "staff", "employee": "staff",
        "hr_payroll": "hr_payroll", "payroll": "hr_payroll",
    }

    csv_files = (glob.glob(os.path.join(sage_root, "*.csv")) +
                 glob.glob(os.path.join(sage_root, "*.CSV")))

    for csv_path in csv_files:
        stem = os.path.splitext(os.path.basename(csv_path))[0].lower().replace(" ", "_").replace("-", "_")
        entity_name = _ALIASES.get(stem)
        if not entity_name or entity_name not in entity_names:
            continue

        rows_out = []
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                available = reader.fieldnames or []
                for raw in reader:
                    mapped = field_maps.map_row(dict(raw), entity_name, list(available))
                    if mapped:
                        rows_out.append(mapped)
                    if dry_run and len(rows_out) >= 10:
                        break
        except Exception as exc:
            log.warning(f"CSV read error {csv_path}: {exc}")

        datasets[entity_name] = rows_out
        print(f"  {entity_name:<30} {len(rows_out):>6} rows  (from {os.path.basename(csv_path)})")

    return datasets


# ---------------------------------------------------------------------------
# Pretty print helpers
# ---------------------------------------------------------------------------

def _print_progress(step: int, total: int, label: str) -> None:
    print(f"\n[{step}/{total}] {label}", flush=True)


def _print_summary(datasets: Dict[str, List]) -> None:
    print("\nINGESTION COMPLETE")
    print("-" * 50)
    total = 0
    for entity, rows in sorted(datasets.items()):
        n = len(rows)
        total += n
        bar = "✓" if n > 0 else "–"
        print(f"  {bar}  {entity:<30} {n:>6} rows")
    print("-" * 50)
    print(f"  {'TOTAL':<32} {total:>6} rows\n")


def _print_dry_run(datasets: Dict[str, List]) -> None:
    from tabulate import tabulate
    print("\n[DRY RUN — no data written]\n")
    for entity, rows in datasets.items():
        if not rows:
            print(f"  {entity}: no rows\n")
            continue
        print(f"  {entity} (first {min(len(rows), 10)} rows):")
        headers = list(rows[0].keys())[:8]
        table_data = [[str(r.get(h, ""))[:30] for h in headers] for r in rows[:10]]
        print(tabulate(table_data, headers=headers, tablefmt="simple"))
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sage 50 2013 (Peachtree) → Synbot data ingestion pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", required=True,
                        help='Path to Sage data folder (e.g. "D:\\Sage Data 1") or .ptb backup file')
    parser.add_argument("--company",
                        help='Company subfolder name (e.g. plaphaen). '
                             'Required for btrieve mode unless --step discover.')
    parser.add_argument("--step", choices=["discover"],
                        help="discover: show schema + companies, no DB writes")
    parser.add_argument("--entity", default="all",
                        help='Entity to load: all | customers | vendors | '
                             'chart_of_accounts | items | stock_on_hand | sales_invoices | '
                             'sales_invoice_lines | purchase_orders | '
                             'inventory_transactions | gl_journal_entries | staff | hr_payroll')
    parser.add_argument("--dry-run", action="store_true",
                        help="Print first 10 rows per entity. No DB writes.")
    parser.add_argument("--upload", metavar="URL",
                        help="Backend base URL. Use http://localhost:8000 to hit FastAPI directly "
                             "(bypasses nginx and avoids SSL redirect). Self-signed cert errors "
                             "are suppressed automatically.")
    parser.add_argument("--token", metavar="JWT",
                        help="Bearer token for --upload (admin/finance role required)")
    parser.add_argument("--db-url", metavar="POSTGRESQL_URL",
                        help="Direct PostgreSQL URL (alternative to --upload)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show detailed logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    # ── Discover mode ───────────────────────────────────────────────────────
    if args.step == "discover":
        run_discover(args.source)
        return

    # ── Validate load target ────────────────────────────────────────────────
    db_url = args.db_url or os.environ.get("DATABASE_URL")
    if not args.dry_run and not args.upload and not db_url:
        parser.error(
            "Specify a load target: --upload URL --token JWT   or   --db-url POSTGRESQL_URL\n"
            "Or use --dry-run to preview without loading."
        )

    if args.upload and not args.token:
        parser.error("--token is required when --upload is specified")

    # ── Determine entity list ───────────────────────────────────────────────
    import field_maps
    all_entities = list(field_maps.ENTITY_MAPS.keys())
    if args.entity.strip().lower() == "all":
        entity_names = all_entities
    else:
        entity_names = [e.strip() for e in args.entity.split(",")]
        unknown = [e for e in entity_names if e not in field_maps.ENTITY_MAPS]
        if unknown:
            parser.error(f"Unknown entity names: {unknown}. Valid: {all_entities}")

    # ── Phase 1: Detect source ──────────────────────────────────────────────
    _print_progress(1, 4, f"Detecting source format ...  ({args.source})")
    t0 = time.time()

    mode, sage_root, tmpdir = phase_detect(args.source)

    if mode == "unknown":
        print(f"\nERROR: Cannot detect format of '{args.source}'.")
        print("Expected: a folder containing FILE.DDF + FIELD.DDF  or  CSV files.")
        print("Run with --step discover for diagnosis.")
        sys.exit(1)

    print(f"  Format : {mode.upper()}   Root: {sage_root}")

    # ── Phase 2: Parse schema ───────────────────────────────────────────────
    datasets: Dict[str, List] = {}
    schema = {}

    if mode == "btrieve":
        if not args.company:
            from sage50 import detector
            companies = detector.list_companies(sage_root)
            if len(companies) == 1:
                args.company = list(companies.keys())[0]
                print(f"  Auto-selected company: {args.company} ({list(companies.values())[0]})")
            else:
                print("\nMultiple companies found — specify one with --company:")
                for folder, label in companies.items():
                    print(f"  --company {folder:<16}  ({label})")
                sys.exit(1)

        _print_progress(2, 4, f"Parsing DDF schema ...  (company: {args.company})")
        schema = phase_parse_schema(sage_root, args.company)
        print(f"  {len(schema)} tables in schema for company '{args.company}'")

    elif mode == "csv":
        _print_progress(2, 4, "CSV mode — no schema parsing needed")

    # ── Phase 3: Extract ────────────────────────────────────────────────────
    _print_progress(3, 4,
                    "Reading company data ..." + (" [DRY RUN]" if args.dry_run else ""))

    if mode == "btrieve":
        datasets = phase_extract(sage_root, schema, args.company, entity_names, args.dry_run)
    elif mode == "csv":
        datasets = run_csv_mode(sage_root, entity_names, args.dry_run)

    if args.dry_run:
        _print_dry_run(datasets)
        if tmpdir:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        return

    total_rows = sum(len(v) for v in datasets.values())
    if total_rows == 0:
        print("\nNo rows extracted. Check --company name or run --step discover.")
        if tmpdir:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        sys.exit(1)

    # ── Phase 4: Load ────────────────────────────────────────────────────────
    _print_progress(4, 4, "Loading into Synbot ...")

    result = {}
    if args.upload:
        result = phase_load_api(datasets, args.upload, args.token)
        if isinstance(result, dict):
            status = result.get("status", "unknown")
            inserted = result.get("total_rows_inserted", "?")
            print(f"  API status: {status}   rows inserted: {inserted}")
            if result.get("datasets"):
                for ds in result["datasets"]:
                    ft = ds.get("file_type", ds.get("file", "?"))
                    n  = ds.get("rows_inserted", "?")
                    st = ds.get("status", "?")
                    print(f"    {ft:<30} {str(n):>6}   [{st}]")
    elif db_url:
        result = phase_load_db(datasets, db_url)

    _print_summary(datasets)

    elapsed = round(time.time() - t0, 1)
    print(f"Total time: {elapsed}s\n")

    if tmpdir:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
