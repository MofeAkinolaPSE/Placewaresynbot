"""detector.py — Auto-detect Sage 50 data source format.

Supported formats:
  btrieve  — folder contains FILE.DDF + FIELD.DDF (Pervasive PSQL binary)
  csv      — folder contains .csv files exported from Sage 50
  ptb      — .ptb backup file (ZIP archive); extracted and re-detected
  unknown  — nothing recognisable found
"""
from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from typing import Optional, Tuple

log = logging.getLogger("detector")

# Company subfolder names from actual Sage Data 1 scan
KNOWN_COMPANIES = {
    "planigli": "Placeware Nigeria Limited",
    "plaphaen": "Placeware Pharma Enterprise",
    "scadiace": "Scancare Diagnostic",
    "octltd":   "Octa Pharma Ltd",
    "topenelt": "Top Chale Energy Ltd",
    "abcngltd": "ABC Nigeria Ltd",
    "xyzltd":   "XYZ Ltd",
    "busht":    "Busht",
    "sbcngitd": "SBC Nigeria",
    "sample":   "Sage Sample Company",
}


def detect(source_path: str) -> Tuple[str, str, Optional[str]]:
    """Return (mode, resolved_root, ptb_tempdir).

    mode:
      'btrieve'  — source_path (or extracted PTB) contains DDF files
      'csv'      — source_path contains CSV files
      'unknown'  — cannot determine format

    resolved_root: actual folder to work with (may differ from source_path after PTB extract)
    ptb_tempdir:   temp dir to clean up after use (only set when mode was 'ptb')
    """
    source_path = os.path.abspath(source_path)

    # --- .ptb file ---
    if os.path.isfile(source_path) and source_path.lower().endswith(".ptb"):
        return _handle_ptb(source_path)

    # --- .zip file (treat like ptb) ---
    if os.path.isfile(source_path) and source_path.lower().endswith(".zip"):
        return _handle_ptb(source_path)

    # --- directory ---
    if os.path.isdir(source_path):
        mode = _probe_directory(source_path)
        return mode, source_path, None

    log.error(f"Source path does not exist or is not a supported type: {source_path}")
    return "unknown", source_path, None


def _handle_ptb(ptb_path: str) -> Tuple[str, str, str]:
    """Extract a .ptb (ZIP) to a temp dir and probe the contents."""
    log.info(f"Extracting PTB backup: {ptb_path}")
    tmp = tempfile.mkdtemp(prefix="sage50_ptb_")
    try:
        with zipfile.ZipFile(ptb_path, "r") as zf:
            zf.extractall(tmp)
    except zipfile.BadZipFile:
        log.error(f"{ptb_path} is not a valid ZIP/PTB archive")
        return "unknown", ptb_path, tmp

    mode = _probe_directory(tmp)
    log.info(f"PTB extracted to {tmp} — detected mode: {mode}")
    return mode, tmp, tmp


def _probe_directory(folder: str) -> str:
    """Return 'btrieve', 'csv', or 'unknown' for a directory."""
    entries_lower = {e.lower() for e in os.listdir(folder)}

    if "file.ddf" in entries_lower and "field.ddf" in entries_lower:
        log.info(f"Btrieve/Pervasive PSQL database detected in: {folder}")
        return "btrieve"

    # Check subfolders for DDF files (DDF sometimes in a subdirectory)
    for sub in os.listdir(folder):
        sub_path = os.path.join(folder, sub)
        if os.path.isdir(sub_path):
            sub_entries = {e.lower() for e in os.listdir(sub_path)}
            if "file.ddf" in sub_entries and "field.ddf" in sub_entries:
                log.info(f"Btrieve/Pervasive PSQL database detected in subfolder: {sub_path}")
                return "btrieve"

    # Check for CSVs
    csv_count = sum(1 for e in entries_lower if e.endswith(".csv"))
    if csv_count >= 1:
        log.info(f"CSV mode detected: {csv_count} CSV files in {folder}")
        return "csv"

    return "unknown"


def list_companies(sage_root: str) -> dict:
    """Return {subfolder_name: company_label} for subfolders that contain .DAT files."""
    found = {}
    try:
        for entry in sorted(os.listdir(sage_root)):
            sub = os.path.join(sage_root, entry)
            if not os.path.isdir(sub):
                continue
            # Count .DAT files in subfolder (must have at least 3 to be a real company)
            dat_count = sum(1 for f in os.listdir(sub) if f.lower().endswith(".dat"))
            if dat_count >= 3:
                label = KNOWN_COMPANIES.get(entry.lower(), f"Unknown ({entry})")
                found[entry] = label
    except OSError:
        pass
    return found
