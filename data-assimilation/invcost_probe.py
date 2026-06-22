"""invcost_probe.py — Scan INVCOST.DAT to identify record size and field offsets.

Run from the data-assimilation/ folder:
    python invcost_probe.py

Outputs:
  - Which candidate record sizes produce readable pharma product names
  - Hex dump of first data record for the winning record size
  - Attempts to find cost/price doubles and category strings
"""
import os
import struct
import sys

DAT_NIGH = r"C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\Installer Files\DAT files\PlacewareNig\INVCOST.DAT"
DAT_PHA  = r"C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\Installer Files\DAT files\PlacewarePha\INVCOST.DAT"

PAGE      = 8192
REC_START = 22
CANDIDATES = [152, 190, 256, 304, 380, 456, 512, 608, 760, 1016, 1078]


def lstr(buf: bytes, off: int) -> str:
    if off + 2 > len(buf):
        return ""
    ln = struct.unpack_from("<H", buf, off)[0]
    if not (3 <= ln <= 80):
        return ""
    s = buf[off + 2 : off + 2 + ln]
    if len(s) < ln:
        return ""
    null = s.find(0)
    s = s[:null] if null >= 0 else s
    try:
        t = s.decode("latin-1").strip()
    except Exception:
        return ""
    alpha = sum(c.isalpha() for c in t)
    return t if alpha >= 3 else ""


def probe_file(path: str, label: str) -> None:
    if not os.path.exists(path):
        print(f"  {label}: FILE NOT FOUND — {path}")
        return

    size = os.path.getsize(path)
    print(f"\n{'='*60}")
    print(f"  {label}: {path}")
    print(f"  Size: {size:,} bytes  ({size/1024/1024:.2f} MB)")

    data = open(path, "rb").read()
    num_pages = len(data) // PAGE
    print(f"  Pages (8192-byte): {num_pages}")

    best_size = None
    best_hits = []

    for rec_size in CANDIDATES:
        hits = []
        for p in range(1, min(num_pages, 300)):
            page = data[p * PAGE : (p + 1) * PAGE]
            if not lstr(page, REC_START):
                continue
            cur = REC_START
            while cur + rec_size <= PAGE and len(hits) < 8:
                v = lstr(page[cur : cur + rec_size], 0)
                if v and v not in hits:
                    hits.append(v)
                cur += rec_size
            if len(hits) >= 8:
                break

        tag = "<== BEST?" if len(hits) >= 5 else ""
        print(f"  rec={rec_size:4d}: {hits[:5] or '(none)'}  {tag}")

        if len(hits) > len(best_hits):
            best_hits = hits
            best_size = rec_size

    if best_size is None:
        print("  No readable records found with any candidate size.")
        return

    print(f"\n  >>> Winning rec_size: {best_size} ({len(best_hits)} unique names found)")

    # Hex dump of first data record at winning size
    print(f"\n  --- Hex dump of first data record (rec_size={best_size}) ---")
    for p in range(1, min(num_pages, 300)):
        page = data[p * PAGE : (p + 1) * PAGE]
        if not lstr(page, REC_START):
            continue
        rec = page[REC_START : REC_START + best_size]
        print(f"  Product name (offset 0): {lstr(rec, 0)!r}")
        for i in range(0, min(len(rec), best_size), 16):
            chunk = rec[i : i + 16]
            hex_p = " ".join(f"{b:02x}" for b in chunk)
            asc_p = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"  {i:04x}: {hex_p:<48}  {asc_p}")
        break

    # Try to find cost/price IEEE doubles at various offsets
    print(f"\n  --- Scanning for IEEE double values (cost/price) in first record ---")
    for p in range(1, min(num_pages, 300)):
        page = data[p * PAGE : (p + 1) * PAGE]
        if not lstr(page, REC_START):
            continue
        rec = page[REC_START : REC_START + best_size]
        for off in range(0, len(rec) - 8, 4):
            val = struct.unpack_from("<d", rec, off)[0]
            if 0.01 < val < 1_000_000 and val == val:  # non-NaN, non-inf, plausible price
                print(f"  Offset {off:4d} (0x{off:04x}): {val:.4f}  <-- possible price/cost")
        break

    # Scan for short LSTRING fields (category, unit) after the item name
    print(f"\n  --- Scanning for short LSTRING fields (category/unit) ---")
    for p in range(1, min(num_pages, 300)):
        page = data[p * PAGE : (p + 1) * PAGE]
        if not lstr(page, REC_START):
            continue
        rec = page[REC_START : REC_START + best_size]
        item_name = lstr(rec, 0)
        if not item_name:
            break
        # Start scanning from after the item name LSTRING
        name_len = struct.unpack_from("<H", rec, 0)[0]
        scan_start = 2 + name_len
        for off in range(scan_start, min(len(rec) - 2, scan_start + 200)):
            ln = struct.unpack_from("<H", rec, off)[0]
            if 2 <= ln <= 20:
                s = rec[off + 2 : off + 2 + ln]
                if len(s) == ln:
                    try:
                        t = s.decode("latin-1").strip()
                        alpha = sum(c.isalpha() for c in t)
                        printable = sum(32 <= b < 127 for b in s)
                        if alpha >= 1 and printable / ln >= 0.85:
                            print(f"  Offset {off:4d} (0x{off:04x}): LSTRING({ln}) = {t!r}  <-- possible category/unit")
                    except Exception:
                        pass
        break


def main() -> None:
    probe_file(DAT_NIGH, "PlacewareNig")
    probe_file(DAT_PHA,  "PlacewarePha")


if __name__ == "__main__":
    main()
