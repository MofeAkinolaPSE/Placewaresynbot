"""hard_reader.py — Direct binary readers for essential Sage 50 2013 DAT files.

Used when FIELD.DDF parsing fails (standard for Pervasive PSQL v10).
All field positions confirmed by binary analysis of actual planigli/plaphaen data.

Page layout (confirmed by binary probing):
    page_size  = 8192 bytes
    rec_start  = 22   bytes from page start (first record offset in each data page)
    Data pages = pages where LSTRING at page_offset=rec_start has valid printable content

LSTRING format: [length: uint16 LE][string_data: length bytes]

plaphaen note: uses page-type byte 0x12 (vs planigli's 0xE5).  Vendor LSTRINGs are
null-padded to a max field width (e.g. len=59 but only 20 printable chars before null).
Customer records are scattered across B-tree node pages; a scan-based fallback
extracts names directly from all 0x12 pages.
"""
from __future__ import annotations

import os
import re
import struct
from typing import Dict, Iterator, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Hard-coded schemas — field offsets within each logical record
# ---------------------------------------------------------------------------

# Key: entity name → schema dict
# Field spec: (rec_offset, read_mode)
#   "lstring"              : read LSTRING at offset, return string
#   "lstring_skip2"        : read LSTRING at offset, skip first 2 bytes of content
#   "lstring_until_null"   : read LSTRING at offset, return content before first null byte

SCHEMAS: Dict[str, Dict] = {

    "customers": {
        # Confirmed: planigli/CUSTOMER.DAT, rec_size=892, page_size=8192, rec_start=22
        # Offsets verified by direct byte analysis on real planigli data.
        # LSTRING header (2 len bytes) at rec_off; string data follows at rec_off+2.
        "dat_files": ["CUSTOMER.DAT", "customer.dat"],
        "page_size": 8192,
        "rec_start": 22,
        "rec_size":  892,
        "min_id_len": 3,
        "max_id_len": 30,
        "page_id_needs_alpha": True,   # customer IDs are names, not pure digits
        "fields": [
            ("CustId",       0,   "lstring"),   # short name / customer ID
            ("Telephone1",   25,  "lstring"),   # phone; data at offset 27
            ("Name",         781, "lstring"),   # legal/full name; data at offset 783
            ("Contact",      813, "lstring"),   # contact person; data at offset 815
            ("EmailAddress", 826, "lstring"),   # email; data at offset 828
        ],
        # Fallback for plaphaen-style files: scan pages of type 0x12 for company names
        "scan_fallback": {
            "page_type_byte": 0x12,
            "min_name_len":   6,
            "max_name_len":   50,
        },
    },

    "chart_of_accounts": {
        # Confirmed: planigli/CHART.DAT, rec_size=1161
        # GL code at rec_off=0 (5-char numeric), name at rec_off=10 (skip 2-byte prefix)
        # Example: AccountID='12301', Description='Measles,Mumps & Rubella Vac'
        "dat_files": ["CHART.DAT", "chart.dat"],
        "page_size": 8192,
        "rec_start": 22,
        "rec_size":  1161,
        "min_id_len": 3,
        "max_id_len": 8,
        "page_id_all_digits": True,   # GL codes are pure numeric strings
        "fields": [
            ("AccountID",   0,  "lstring"),
            ("Description", 10, "lstring_skip2"),
        ],
    },

    "vendors": {
        # Confirmed: planigli/VENDOR.DAT, rec_size=609
        # planigli: VendorId at rec_off=0 IS the company name (descriptive IDs, short).
        # plaphaen: VendorId at rec_off=0 is a null-padded LSTRING (len=59) with
        #   20-char name followed by null padding — use lstring_until_null mode.
        # max_id_len=80 covers both short planigli IDs and plaphaen's 59-byte padded names.
        "dat_files": ["VENDOR.DAT", "vendor.dat"],
        "page_size": 8192,
        "rec_start": 22,
        "rec_size":  609,
        "min_id_len": 2,
        "max_id_len": 80,
        "page_id_needs_alpha": True,
        "fields": [
            ("VendorId",   0, "lstring_until_null"),  # maps to vendor_id
            ("VendorName", 0, "lstring_until_null"),  # same field, maps to vendor_name
        ],
    },

    "items": {
        # Confirmed: planigli/LINEITEM.DAT, rec_size=1078, page_size=8192, rec_start=22
        # Product name LSTRING at rec_off=0 is null-padded (len up to 60, content 10-20 chars).
        # Trailing batch codes like (O), (N), (L) are stripped by lstring_strip_batch mode
        # to produce clean deduplicated product names for the inventory catalog.
        # Data pages have no consistent type byte; LSTRING-at-22 detection is used directly.
        #
        # Tier 2 additions (binary probe confirmed):
        #   ExpiryDate — LSTRING at variable offset [30..150]; pharmaceutical expiry MM/YY
        #   LotCode    — LSTRING at variable offset [560..730]; supplier lot/batch number
        "dat_files": ["LINEITEM.DAT", "lineitem.dat"],
        "page_size": 8192,
        "rec_start": 22,
        "rec_size":  1078,
        "min_id_len": 5,
        "max_id_len": 65,
        "page_id_needs_alpha": True,
        "fields": [
            ("ItemID",      0, "lstring_strip_batch"),
            ("Description", 0, "lstring_strip_batch"),
            ("ExpiryDate",  0, "scan_date"),
            ("LotCode",     0, "scan_lot_code"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _read_lstring(data: bytes, offset: int) -> str:
    """Read a Btrieve LSTRING (LE16 length prefix + data bytes)."""
    if offset + 2 > len(data):
        return ""
    ln = struct.unpack_from("<H", data, offset)[0]
    if not (1 <= ln <= 500):
        return ""
    end = offset + 2 + ln
    if end > len(data):
        return ""
    raw = data[offset + 2 : end]
    return raw.decode("latin-1", errors="replace")


def _is_printable_enough(s: bytes, threshold: float = 0.70) -> bool:
    if not s:
        return False
    printable = sum(1 for b in s if 32 <= b < 127) / len(s)
    return printable >= threshold


def _clean_lstring(val: str) -> str:
    """Strip null/high/control bytes; return empty string if result is not legible."""
    cleaned = val.replace("\x00", "").strip(" \xff")
    if not cleaned:
        return ""
    printable = sum(1 for c in cleaned if 32 <= ord(c) < 127) / len(cleaned)
    return cleaned if printable >= 0.70 else ""


def _read_field(data: bytes, offset: int, mode: str) -> str:
    """Extract a field value using the given read mode."""
    if mode == "lstring":
        val = _read_lstring(data, offset)
        return _clean_lstring(val)

    if mode == "lstring_skip2":
        val = _read_lstring(data, offset)
        trimmed = val[2:] if len(val) > 2 else ""
        return _clean_lstring(trimmed)

    if mode == "lstring_until_null":
        # For null-padded LSTRINGs (plaphaen style): return content before first null.
        val = _read_lstring(data, offset)
        if not val:
            return ""
        null_pos = val.find("\x00")
        if null_pos >= 0:
            val = val[:null_pos]
        return _clean_lstring(val)

    if mode == "lstring_strip_batch":
        # Like lstring_until_null, but also strips trailing pharma batch codes: (O), (N), (L) etc.
        # Handles both complete "(X)" and truncated-by-null "(X" at end of string.
        val = _read_lstring(data, offset)
        if not val:
            return ""
        null_pos = val.find("\x00")
        if null_pos >= 0:
            val = val[:null_pos]
        val = _clean_lstring(val)
        if val:
            val = re.sub(r"\s*\([A-Za-z0-9/]{1,4}\)\s*$", "", val).strip()
            val = re.sub(r"\s*\([A-Za-z0-9/]{1,3}$", "", val).strip()
        return val

    if mode == "scan_date":
        # Scan record bytes [30..150) for the first LSTRING that looks like an expiry date
        # (format MM/YY or MM/YYYY — digits separated by '/').  Offset param is ignored.
        for off in range(30, min(150, len(data) - 2)):
            ln = struct.unpack_from("<H", data, off)[0]
            if 4 <= ln <= 12 and off + 2 + ln <= len(data):
                raw = data[off + 2 : off + 2 + ln]
                null = raw.find(0)
                text_bytes = raw[:null] if null >= 0 else raw
                if len(text_bytes) >= 4:
                    pct = sum(1 for b in text_bytes if 32 <= b < 127) / len(text_bytes)
                    s = text_bytes.decode("latin-1", "replace").strip()
                    if pct >= 0.85 and "/" in s and s[0].isdigit():
                        digits = sum(c.isdigit() for c in s)
                        parts = s.split("/")
                        if (
                            digits >= 2
                            and len(parts) >= 2
                            and parts[0].isdigit()
                            and any(c.isdigit() for c in parts[1])
                        ):
                            month = parts[0].zfill(2)
                            year_raw = "".join(c for c in parts[1] if c.isdigit())
                            # Normalise 2-digit year to 4-digit (20xx)
                            year = f"20{year_raw}" if len(year_raw) == 2 else year_raw
                            # Return ISO date (first of month); required by expiry_monitoring_agent
                            return f"{year}-{month}-01"
        return ""

    if mode == "scan_lot_code":
        # Scan record bytes [560..730) for the first LSTRING that looks like a lot/batch code:
        # alphanumeric, no spaces, no slashes, mix of letters and digits, length 5-15.
        # Offset param is ignored.
        for off in range(560, min(730, len(data) - 2)):
            ln = struct.unpack_from("<H", data, off)[0]
            if 5 <= ln <= 15 and off + 2 + ln <= len(data):
                raw = data[off + 2 : off + 2 + ln]
                null = raw.find(0)
                text_bytes = raw[:null] if null >= 0 else raw
                if len(text_bytes) >= 5:
                    pct = sum(1 for b in text_bytes if 32 <= b < 127) / len(text_bytes)
                    s = text_bytes.decode("latin-1", "replace").strip()
                    if pct >= 0.90 and " " not in s and "/" not in s:
                        alpha = sum(c.isalpha() for c in s)
                        digit = sum(c.isdigit() for c in s)
                        if alpha >= 1 and digit >= 1:
                            return re.sub(r"[^A-Za-z0-9.\-]", "", s)
        return ""

    if mode.startswith("char:"):
        width = int(mode.split(":")[1])
        raw = data[offset : offset + width]
        return raw.decode("latin-1", errors="replace").rstrip("\x00 ")

    return ""


def _is_data_page(page: bytes, rec_start: int, schema: Dict) -> bool:
    """Return True if this page has a valid record-ID LSTRING at rec_start."""
    min_len = schema["min_id_len"]
    max_len = schema["max_id_len"]
    needs_alpha  = schema.get("page_id_needs_alpha", False)
    needs_digits = schema.get("page_id_all_digits", False)

    if rec_start + 2 > len(page):
        return False
    ln = struct.unpack_from("<H", page, rec_start)[0]
    if not (min_len <= ln <= max_len):
        return False
    s = page[rec_start + 2 : rec_start + 2 + ln]
    if len(s) < min_len:
        return False

    if needs_digits:
        return all(48 <= b <= 57 for b in s)

    # For null-padded LSTRINGs, evaluate only the pre-null content.
    null_pos = s.find(0)
    content = s[:null_pos] if null_pos >= 0 else s
    if not content:
        return False

    if not _is_printable_enough(content, 0.75):
        return False
    if needs_alpha:
        alpha_count = sum(1 for b in content if (65 <= b <= 90) or (97 <= b <= 122))
        if alpha_count < 3:
            return False
    return True


# ---------------------------------------------------------------------------
# Core record iterator
# ---------------------------------------------------------------------------

def _is_valid_primary_key(val: str, schema: Dict) -> bool:
    """Return True if a primary key value looks like real data (not garbage)."""
    if not val:
        return False
    if len(val) < schema.get("min_id_len", 1):
        return False
    if schema.get("page_id_all_digits"):
        return all(c.isdigit() for c in val)
    if schema.get("page_id_needs_alpha"):
        alpha = sum(1 for c in val if c.isalpha())
        return alpha >= 3
    return True


def iter_records(
    dat_path: str,
    schema: Dict,
) -> Iterator[Dict[str, str]]:
    """Yield row dicts from a .DAT file using a hard-coded schema."""
    page_size = schema["page_size"]
    rec_start = schema["rec_start"]
    rec_size  = schema["rec_size"]
    fields    = schema["fields"]

    try:
        with open(dat_path, "rb") as f:
            data = f.read()
    except OSError:
        return

    num_pages = len(data) // page_size
    seen_ids: set = set()

    for p in range(num_pages):
        page_off = p * page_size
        page = data[page_off : page_off + page_size]

        if not _is_data_page(page, rec_start, schema):
            continue

        cursor = rec_start
        while cursor + rec_size <= page_size:
            rec = page[cursor : cursor + rec_size]

            row: Dict[str, str] = {}
            for field_name, field_off, field_mode in fields:
                val = _read_field(rec, field_off, field_mode)
                row[field_name] = val

            primary_key = fields[0][0]
            primary_val = row.get(primary_key, "")

            if _is_valid_primary_key(primary_val, schema) and primary_val not in seen_ids:
                seen_ids.add(primary_val)
                yield row

            cursor += rec_size


# ---------------------------------------------------------------------------
# Scan-based fallback for files where record layout is unknown (plaphaen customers)
# ---------------------------------------------------------------------------

# Strings that look like company names but are shipping methods / place names
_SCAN_BLOCKLIST = re.compile(
    r"^(?:Hand\s+Deliver|Deliver|Courier|N/?A|Unknown|Test)\b",
    re.IGNORECASE,
)


def _scan_dat_for_names(
    dat_path: str,
    page_type_byte: int,
    page_size: int,
    min_len: int,
    max_len: int,
    max_rows: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Scan all pages of a given type for company-name LSTRINGs.

    Used when the record layout is unknown (e.g. plaphaen CUSTOMER.DAT, which stores
    records across B-tree node pages in a format that resists fixed-stride extraction).
    Returns rows with CustId and Name set to the same company name string.
    """
    try:
        with open(dat_path, "rb") as f:
            data = f.read()
    except OSError:
        return []

    seen: set = set()
    rows: List[Dict[str, str]] = []

    for p in range(len(data) // page_size):
        if data[p * page_size] != page_type_byte:
            continue
        page = data[p * page_size : (p + 1) * page_size]

        off = 0
        while off < page_size - 2:
            ln = struct.unpack_from("<H", page, off)[0]
            if min_len <= ln <= max_len:
                s = page[off + 2 : off + 2 + ln]
                if len(s) == ln:
                    pct = sum(1 for b in s if 32 <= b < 127) / ln
                    alpha = sum(1 for b in s if (65 <= b <= 90) or (97 <= b <= 122))
                    if pct >= 0.90 and alpha >= 3:
                        name = s.decode("latin-1", "replace").strip()
                        if name and name not in seen and not _SCAN_BLOCKLIST.match(name):
                            seen.add(name)
                            rows.append({"CustId": name, "Name": name})
                            if max_rows is not None and len(rows) >= max_rows:
                                return rows
                        off += 2 + ln
                        continue
            off += 1

    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _find_dat(sage_root: str, company: Optional[str], filenames: List[str]) -> Optional[str]:
    """Find a DAT file by trying company folder first, then root."""
    candidates = []
    if company:
        candidates.append(os.path.join(sage_root, company))
    candidates.append(sage_root)

    for base in candidates:
        for fname in filenames:
            path = os.path.join(base, fname)
            if os.path.exists(path):
                return path
    return None


def read_entity(
    entity_name: str,
    sage_root: str,
    company: Optional[str] = None,
    max_rows: Optional[int] = None,
) -> Optional[List[Dict[str, str]]]:
    """Read records for an entity using the hard-coded schema.

    Returns:
        List of row dicts  — success (may be empty if no data pages found)
        None               — entity has no hard-coded schema
    """
    if entity_name == "jrnl_transactions":
        return read_jrnl_transactions(sage_root, company, max_rows)

    if entity_name == "invoice_headers":
        return read_invoice_headers(sage_root, company, max_rows)

    schema = SCHEMAS.get(entity_name)
    if schema is None:
        return None

    dat_path = _find_dat(sage_root, company, schema["dat_files"])
    if dat_path is None:
        return []

    rows: List[Dict[str, str]] = []
    for row in iter_records(dat_path, schema):
        rows.append(row)
        if max_rows is not None and len(rows) >= max_rows:
            break

    # Scan-based fallback: for customer files where B-tree page format prevents
    # fixed-stride extraction (e.g. plaphaen), extract names directly from data pages.
    if not rows and "scan_fallback" in schema:
        fb = schema["scan_fallback"]
        rows = _scan_dat_for_names(
            dat_path,
            page_type_byte=fb["page_type_byte"],
            page_size=schema["page_size"],
            min_len=fb["min_name_len"],
            max_len=fb["max_name_len"],
            max_rows=max_rows,
        )

    return rows


def available_entities() -> List[str]:
    """Return entity names that have hard-coded schemas."""
    return list(SCHEMAS.keys())


def field_names(entity_name: str) -> List[str]:
    """Return the field names produced by the hard reader for an entity."""
    if entity_name == "jrnl_transactions":
        return ["description", "posting_date", "record_id"]
    if entity_name == "invoice_headers":
        return ["name", "reference", "date", "date2"]
    schema = SCHEMAS.get(entity_name)
    if schema is None:
        return []
    return [f[0] for f in schema["fields"]]


# ---------------------------------------------------------------------------
# CONTACTS.DAT — variable-size UUID-keyed records
# ---------------------------------------------------------------------------
# Each record: [14 random bytes][0x52][0x00 0x00][LE16 name_len][name_bytes]
# Phone (Nigerian 0[789]XXXXXXXX) optionally follows the name within 30 bytes.
# Signature byte 0x52 at key position 15 is consistent across all tested records.

_PHONE_RE = re.compile(rb"0[789]\d{8,9}")


def _scan_dat_for_contacts(
    dat_path: str,
    max_rows: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Scan CONTACTS.DAT for contact records using the 0x52 signature."""
    try:
        data = open(dat_path, "rb").read()
    except OSError:
        return []

    seen: set = set()
    rows: List[Dict[str, str]] = []
    i = 0
    while i < len(data) - 20:
        if data[i] == 0x52 and data[i + 1] == 0x00 and data[i + 2] == 0x00:
            ln = struct.unpack_from("<H", data, i + 3)[0]
            if 5 <= ln <= 50:
                name_bytes = data[i + 5 : i + 5 + ln]
                if len(name_bytes) == ln:
                    pct = sum(1 for b in name_bytes if 32 <= b < 127) / ln
                    alpha = sum(1 for b in name_bytes if (65 <= b <= 90) or (97 <= b <= 122))
                    if pct >= 0.85 and alpha >= 2:
                        name = name_bytes.decode("latin-1", "replace").strip()
                        null_pos = name.find("\x00")
                        if null_pos >= 0:
                            name = name[:null_pos].strip()
                        after = data[i + 5 + ln : i + 5 + ln + 30]
                        m = _PHONE_RE.search(after)
                        phone = m.group().decode("ascii") if m else ""
                        if name and name not in seen and not _SCAN_BLOCKLIST.match(name):
                            seen.add(name)
                            rows.append({"ContactName": name, "Phone": phone})
                            if max_rows is not None and len(rows) >= max_rows:
                                return rows
                        i += 5 + ln
                        continue
        i += 1
    return rows


def read_contacts(
    sage_root: str,
    company: Optional[str] = None,
    max_rows: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Read contact records from CONTACTS.DAT."""
    dat_path = _find_dat(sage_root, company, ["CONTACTS.DAT", "contacts.dat"])
    if dat_path is None:
        return []
    return _scan_dat_for_contacts(dat_path, max_rows)


# ---------------------------------------------------------------------------
# ADDRESS.DAT — length-prefixed field records grouped by 'Bill To' label
# ---------------------------------------------------------------------------
# Each address record: ['Bill To'][5-byte header][company][5-byte header][street][5-byte header][city]
# 5-byte header format: [3 bytes metadata][1 byte string_length][1 byte separator=0x00]
# 'Bill To' appears ~1,146 times (one per invoice/transaction); we deduplicate by company name.

def _scan_dat_for_addresses(
    dat_path: str,
    max_rows: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Scan ADDRESS.DAT for billing address groups anchored by 'Bill To' labels."""
    try:
        data = open(dat_path, "rb").read()
    except OSError:
        return []

    def _read_field(pos: int):
        """Read [3-byte meta][1-byte len][1-byte sep=0x00][string]. Returns (string, next_pos)."""
        if pos + 5 > len(data):
            return "", pos
        ln = data[pos + 3]          # length byte is at index 3 of the 5-byte header
        s_start = pos + 5           # string starts after the full 5-byte header
        if s_start + ln > len(data) or not (2 <= ln <= 80):
            return "", pos
        raw = data[s_start : s_start + ln]
        pct = sum(1 for b in raw if 32 <= b < 127) / ln
        if pct < 0.75:              # reject binary garbage
            return "", pos
        val = raw.decode("latin-1", "replace")
        null_pos = val.find("\x00")
        if null_pos >= 0:
            val = val[:null_pos]
        return val.strip(), s_start + ln

    target = b"Bill To"
    seen: set = set()
    rows: List[Dict[str, str]] = []
    i = 0
    while i < len(data) - 120:
        if data[i : i + len(target)] == target:
            pos = i + len(target)
            company, pos = _read_field(pos)
            street,  pos = _read_field(pos)
            city,    _   = _read_field(pos)
            if company and len(company) >= 3 and company not in seen:
                seen.add(company)
                rows.append({"CompanyName": company, "Street": street, "City": city})
                if max_rows is not None and len(rows) >= max_rows:
                    return rows
        i += 1
    return rows


def read_addresses(
    sage_root: str,
    company: Optional[str] = None,
    max_rows: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Read billing address records from ADDRESS.DAT."""
    dat_path = _find_dat(sage_root, company, ["ADDRESS.DAT", "address.dat"])
    if dat_path is None:
        return []
    return _scan_dat_for_addresses(dat_path, max_rows)


# ---------------------------------------------------------------------------
# JRNLHDR.DAT — invoice/transaction headers (binary pattern scanner)
# ---------------------------------------------------------------------------
# JrnlHdr stores one record per posted transaction (Sales Invoice, Payment,
# Journal Entry, etc.) with the customer/payee name, the document reference
# number, and one or two dates. See btrieve_scanner.scan_jrnlhdr_invoices for
# the discovered record pattern (validated against Sage's bundled Bellwether
# Garden Supply sample company — same engine/schema as any Sage 50 US
# Edition / Peachtree install). Dollar amounts are not in this file; they
# live on the JrnlRow GL distribution rows.

def read_invoice_headers(
    sage_root: str,
    company: Optional[str] = None,
    max_rows: Optional[int] = None,
) -> List[Dict[str, str]]:
    """
    Read invoice/transaction header records from JrnlHdr.DAT.

    Returns list of dicts with keys:
        name        – customer/payee name on the transaction
        reference   – Sage-assigned document/invoice number
        date        – primary transaction date, 'YYYY-MM-DD', or '' if not decoded
        date2       – secondary nearby date (purpose unconfirmed), or ''
    """
    try:
        from sage50.btrieve_scanner import scan_jrnlhdr_invoices  # type: ignore
    except ImportError:
        try:
            from btrieve_scanner import scan_jrnlhdr_invoices  # type: ignore
        except ImportError:
            return []

    dat_path = _find_dat(sage_root, company, ["JRNLHDR.DAT", "jrnlhdr.dat"])
    if dat_path is None:
        return []

    raw = scan_jrnlhdr_invoices(dat_path, max_rows=max_rows or 0)

    rows: List[Dict[str, str]] = []
    for r in raw:
        rows.append({
            "name":      r.get("name") or "",
            "reference": r.get("reference") or "",
            "date":      r.get("date") or "",
            "date2":     r.get("date2") or "",
        })
        if max_rows is not None and len(rows) >= max_rows:
            break

    return rows


# ---------------------------------------------------------------------------
# JRNLROW.DAT — GL journal transaction rows (binary Btrieve page scanner)
# ---------------------------------------------------------------------------
# JrnlRow uses 512-byte Btrieve pages with a different record format from the
# other DAT files.  The btrieve_scanner module handles the raw page parsing.
# Fields extracted: description (RowDescription), posting_date, record_id.
# Debit/credit amounts are in an unresolved binary encoding — not yet extracted.

def read_jrnl_transactions(
    sage_root: str,
    company: Optional[str] = None,
    max_rows: Optional[int] = None,
) -> List[Dict[str, str]]:
    """
    Read GL journal row transactions from JRNLROW.DAT via binary page scan.

    Returns list of dicts with keys:
        description   – narration/description text of the GL row
        posting_date  – 'YYYY-MM-DD' string, or '' if not decoded
        record_id     – internal sequence number (str) or ''

    Debit/credit amounts are not yet decoded (binary format unresolved).
    """
    try:
        from sage50.btrieve_scanner import scan_jrnlrow  # type: ignore
    except ImportError:
        try:
            from btrieve_scanner import scan_jrnlrow  # type: ignore
        except ImportError:
            return []

    dat_path = _find_dat(sage_root, company, ["JRNLROW.DAT", "jrnlrow.dat"])
    if dat_path is None:
        return []

    # For small max_rows (dry-run), scan only the first ~5 000 pages (~2.5 MB)
    # to return quickly.  For full runs, scan the entire file.
    scan_pages = 5000 if (max_rows is not None and max_rows <= 50) else 0
    raw = scan_jrnlrow(dat_path, max_pages=scan_pages)

    # Deduplicate by (description, date) — shadow B-tree pages can produce copies
    seen: set = set()
    rows: List[Dict[str, str]] = []
    for r in raw:
        desc = r.get("description", "").strip()
        date = r.get("posting_date") or ""
        if not desc:
            continue
        key = (desc, date)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "description":  desc,
            "posting_date": date,
            "record_id":    str(r.get("record_id") or ""),
        })
        if max_rows is not None and len(rows) >= max_rows:
            break

    return rows
