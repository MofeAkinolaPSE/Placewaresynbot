"""One mapping decides the journal of every posting: the General Ledger's Jrnl column and the
Journals-by-type reports must agree, and every posting must land in exactly one journal."""
import pathlib
import re

from src.fin import journal_map
from src.fin.db import q

FIN = pathlib.Path(__file__).resolve().parents[2] / "src" / "fin"


def _posted_source_types():
    found = set()
    for f in FIN.glob("*.py"):
        for call in re.findall(r"post_system\((.*?)\)\n", f.read_text(encoding="utf-8"), re.S):
            found.update(re.findall(r'source_type="([A-Z_]+)"', call))
    return found


def test_every_posting_source_has_a_journal():
    sources = _posted_source_types()
    assert {"SALES_INVOICE", "CASH_VOUCHER", "FIXED_ASSET", "DATA_CORRECTION"} <= sources  # the scan works
    assert sources - set(journal_map.SOURCE_JOURNAL) == set()


def test_each_code_is_in_exactly_one_journal_report():
    codes = set(journal_map.SOURCE_JOURNAL.values()) | set(journal_map.VOUCHER_JOURNAL.values()) | {journal_map.DEFAULT}
    for c in codes:
        assert sum(c in listed for listed in journal_map.REPORT_CODES.values()) == 1, c
    assert set(journal_map.REPORT_CODES) <= set(journal_map.KEY_CODE.values())


def test_sql_and_python_agree(conn):
    cur = conn.cursor()
    # a stand-in for the vouchers table, visible only inside this rolled-back transaction
    cur.execute("CREATE TEMP TABLE fin_cash_vouchers (id text, kind text)")
    cur.execute("INSERT INTO fin_cash_vouchers VALUES ('v-spend','SPEND'), ('v-recv','RECEIVE'), ('v-xfer','TRANSFER')")
    cases = [(s, None) for s in journal_map.SOURCE_JOURNAL] + [("SOMETHING_NEW", None), (None, None),
             ("CASH_VOUCHER", "v-spend"), ("CASH_VOUCHER", "v-recv"), ("CASH_VOUCHER", "v-xfer")]
    kinds = {"v-spend": "SPEND", "v-recv": "RECEIVE", "v-xfer": "TRANSFER"}
    for st, sid in cases:
        got = q(conn, f"SELECT {journal_map.code_sql('x.st', 'x.sid')} AS c FROM (SELECT %s::text st, %s::text sid) x", (st, sid))[0]["c"]
        assert got == journal_map.journal_code(st, kinds.get(sid)), (st, sid)
    assert journal_map.journal_code("CASH_VOUCHER", "RECEIVE") == "CRJ"
    assert journal_map.journal_code("CASH_VOUCHER", "TRANSFER") == "GENJ"
    assert journal_map.journal_code("DEPRECIATION_RUN") == "FA"
    assert journal_map.journal_code("MIGRATION") == "GENJ"
