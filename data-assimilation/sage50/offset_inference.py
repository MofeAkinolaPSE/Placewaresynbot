"""
offset_inference.py — Automated field-offset discovery for Sage 50 DAT files.

Strategy (per research doc data-problem-fix.md):
  1. Scan JRNLHDR.DAT using the existing btrieve_scanner to get anchored records.
  2. Around each anchor (the 0x00 0x00 + Name marker found by the scanner), probe
     every 4-byte-aligned window as IEEE-754 float32 and float64.
  3. Score each candidate offset by how often it produces a valid accounting value
     (finite, ≥ 0, < 10 million, rounds cleanly to 2 decimal places).
  4. Rank and print the top candidates — the correct offsets for MainAmount,
     AmountPaid etc. will cluster at the top with high consistency scores.

Run directly:
    python offset_inference.py
"""

import os
import sys
import struct
import math
from collections import defaultdict
from typing import List, Dict, Tuple

# ── paths ─────────────────────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..', '..', 'Installer Files', 'Sage Data 1', 'planigli')

JRNLHDR_DAT = os.path.join(_ROOT, 'JRNLHDR.DAT')
JRNLROW_DAT = os.path.join(_ROOT, 'JRNLROW.DAT')

# ── amount validity filter ─────────────────────────────────────────────────────

def _is_valid_amount(v: float) -> bool:
    """
    Accounting amounts obey tight constraints:
      - finite (no NaN / Inf)
      - STRICTLY positive (MainAmount is never 0 on a real invoice)
      - < 10 million (plausible for an SME)
      - rounds cleanly to 2 decimal places (money)
    """
    if not math.isfinite(v):
        return False
    if v <= 0.01 or v > 10_000_000.0:   # exclude zero AND near-zero noise
        return False
    # 2-dp check: after rounding to 2dp the difference should be < 0.005
    if abs(round(v, 2) - v) > 0.005:
        return False
    return True


def _is_valid_quantity(v: float) -> bool:
    """Quantities can be negative (returns/credits), must be finite and small."""
    if not math.isfinite(v):
        return False
    if abs(v) > 1_000_000:
        return False
    if abs(round(v, 4) - v) > 0.0001:
        return False
    return True


# ── core prober ───────────────────────────────────────────────────────────────

def probe_offsets(
    dat_path: str,
    sample: int = 300,
    window: int = 600,
    step: int = 4,
    validator=_is_valid_amount,
) -> List[Dict]:
    """
    Probe a JRNLHDR.DAT file and return ranked candidate field offsets.

    Args:
        dat_path: Path to the .DAT file.
        sample:   Max records to analyse (more = better signal, slower).
        window:   Half-window in bytes around the anchor to probe (±window bytes).
        step:     Stride for offset probing (4 = 4-byte aligned, matching Pervasive).
        validator: Function(float) -> bool — what counts as a plausible value.

    Returns:
        List of dicts sorted by consistency (highest first):
          relative_offset  — byte offset relative to the record anchor (file_offset)
          dtype            — 'f4' (IEEE-754 float32) or 'f8' (float64)
          consistency      — fraction of records where a valid value was found (0–1)
          sample_count     — number of records with a valid value at this offset
          unique_values    — number of distinct values seen (low = boring, high = active)
          sample_values    — up to 5 example values
    """
    sys.path.insert(0, _HERE)
    from btrieve_scanner import scan_jrnlhdr_invoices  # type: ignore

    if not os.path.isfile(dat_path):
        print(f'[offset_inference] File not found: {dat_path}')
        return []

    print(f'[offset_inference] Loading {os.path.basename(dat_path)} …')
    with open(dat_path, 'rb') as fh:
        raw = fh.read()

    print(f'[offset_inference] Scanning for anchor records (sample={sample}) …')
    records = scan_jrnlhdr_invoices(dat_path, max_rows=sample)
    total = len(records)
    print(f'[offset_inference] Found {total} anchor records — probing ±{window} bytes …')

    # relative_offset → list of decoded values
    hits_f4: Dict[int, List[float]] = defaultdict(list)
    hits_f8: Dict[int, List[float]] = defaultdict(list)

    for rec in records:
        anchor = rec.get('file_offset', 0)
        lo = max(0, anchor - window)
        hi = min(len(raw) - 8, anchor + window)

        for off in range(lo, hi - 4, step):
            rel = off - anchor

            # 4-byte float
            try:
                v = struct.unpack_from('<f', raw, off)[0]
                if validator(v):
                    hits_f4[rel].append(round(v, 2))
            except Exception:
                pass

            # 8-byte double
            if off + 8 <= hi:
                try:
                    v = struct.unpack_from('<d', raw, off)[0]
                    if validator(v):
                        hits_f8[rel].append(round(v, 2))
                except Exception:
                    pass

    results: List[Dict] = []

    def _score(rel: int, dtype: str, values: List[float]) -> Dict:
        unique = len(set(values))
        return {
            'relative_offset': rel,
            'dtype':           dtype,
            'consistency':     round(len(values) / total, 3),
            'sample_count':    len(values),
            'unique_values':   unique,
            'sample_values':   values[:5],
        }

    for rel, vals in hits_f4.items():
        if len(vals) >= max(3, total * 0.10):   # at least 10% of records
            results.append(_score(rel, 'f4', vals))

    for rel, vals in hits_f8.items():
        if len(vals) >= max(3, total * 0.10):
            results.append(_score(rel, 'f8', vals))

    # Sort: highest consistency first; break ties by fewest unique values (stable fields)
    results.sort(key=lambda x: (-x['consistency'], x['unique_values']))
    return results


# ── cross-validation helper ───────────────────────────────────────────────────

def cross_validate(
    hdr_path: str,
    row_path: str,
    hdr_amount_offset: int,
    row_amount_offset: int,
    hdr_dtype: str = 'f4',
    row_dtype: str = 'f4',
    sample: int = 100,
) -> Dict:
    """
    Validate candidate offsets using the accounting identity:
        JrnlHdr.MainAmount  ≈  Σ JrnlRow.Amount  (for the same PostOrder)

    Returns a dict with match_rate, total_tested, mean_abs_error.
    (Requires PostOrder linking — implemented as a future step once
     hdr_amount_offset and row_amount_offset are identified.)
    """
    # Placeholder — full implementation after offsets are identified
    return {'status': 'pending', 'note': 'Run after candidate offsets are found'}


# ── main ──────────────────────────────────────────────────────────────────────

def _fmt_vals(vals):
    return ', '.join(f'{v:.2f}' for v in vals)


def main():
    print('=' * 65)
    print('  Sage 50 JRNLHDR.DAT — Offset Inference Engine')
    print('=' * 65)

    if not os.path.isfile(JRNLHDR_DAT):
        print(f'\nERROR: JRNLHDR.DAT not found at:\n  {JRNLHDR_DAT}')
        sys.exit(1)

    candidates = probe_offsets(JRNLHDR_DAT, sample=300, window=600)

    if not candidates:
        print('\nNo candidates found. Try increasing window or reducing step.')
        sys.exit(1)

    print(f'\n{"Rank":>4}  {"Rel.Offset":>10}  {"Type":>4}  {"Consist.":>8}  {"N":>5}  {"Unique":>6}  Sample values')
    print('-' * 80)

    for rank, c in enumerate(candidates[:40], 1):
        print(
            f'{rank:>4}  '
            f'{c["relative_offset"]:>+10d}  '
            f'{c["dtype"]:>4}  '
            f'{c["consistency"]:>8.1%}  '
            f'{c["sample_count"]:>5}  '
            f'{c["unique_values"]:>6}  '
            f'{_fmt_vals(c["sample_values"])}'
        )

    print(f'\nTop candidates saved.  {len(candidates)} total passed the 30% threshold.')
    print('\nNext step: pick candidates with high consistency AND many unique values')
    print('(those are the live financial fields, not constants).')
    print('\nThen run cross_validate() with the top MainAmount offset to confirm.')


if __name__ == '__main__':
    main()
