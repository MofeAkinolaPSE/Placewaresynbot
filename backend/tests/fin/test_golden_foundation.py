"""Golden Financial Tests 001-010 (Financial Foundation Implementation Pack §48-57).

These prove the kernel's promise: a valid financial event becomes a balanced,
auditable journal that appears in the GL and Trial Balance - and nothing
invalid can get in, even by going around the Python layer.
"""
import datetime as dt

import psycopg2
import pytest

from src.fin import accounts, ledger, periods, posting
from src.fin.db import q, q1
from src.fin.errors import FinError

D = dt.date(2026, 7, 15)


def _jv(accts, dr, cr, amt_dr=100000, amt_cr=None):
    return [{"account_id": accts[dr]["id"], "debit": amt_dr},
            {"account_id": accts[cr]["id"], "credit": amt_cr if amt_cr is not None else amt_dr}]


def test_001_manual_journal_posts_to_gl_and_tb(conn, make_entity):
    ctx, a = make_entity()
    j = posting.create_manual(conn, ctx, journal_date=D, description="Cash sale", lines=_jv(a, "10100", "40000"))
    j = posting.post_manual(conn, ctx, j["id"])
    assert j["status"] == "POSTED" and str(j["total_debit"]) == "100000.00" == str(j["total_credit"])
    act = ledger.account_activity(conn, ctx.entity_id, str(a["10100"]["id"]), D, D)
    assert str(act["closing"]) == "100000.00" and act["count"] == 1
    tb = ledger.trial_balance(conn, ctx.entity_id, dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    assert tb["balanced"] and str(tb["totals"]["closing_debit"]) == "100000.00"
    assert q1(conn, "SELECT 1 FROM fin_audit_events WHERE entity_id=%s AND action='JOURNAL_POSTED'", (str(j["id"]),))


def test_002_unbalanced_journal_rejected_without_mutation(conn, make_entity):
    ctx, a = make_entity()
    j = posting.create_manual(conn, ctx, journal_date=D, description="Bad", lines=_jv(a, "10100", "40000", 100000, 90000))
    with pytest.raises(FinError) as e:
        posting.post_manual(conn, ctx, j["id"])
    assert e.value.code == "UNBALANCED_JOURNAL"
    assert q1(conn, "SELECT status FROM fin_journals WHERE id=%s", (j["id"],))["status"] == "DRAFT"
    assert not q(conn, "SELECT 1 FROM fin_v_general_ledger WHERE journal_id=%s", (j["id"],))
    assert not q1(conn, "SELECT 1 FROM fin_audit_events WHERE entity_id=%s AND action='JOURNAL_POSTED'", (str(j["id"]),))


def test_002b_database_refuses_unbalanced_post_even_bypassing_python(conn, make_entity):
    ctx, a = make_entity()
    j = posting.create_manual(conn, ctx, journal_date=D, description="Bad", lines=_jv(a, "10100", "40000", 100, 90))
    with pytest.raises(psycopg2.Error) as e:
        with conn.cursor() as cur:
            cur.execute("UPDATE fin_journals SET status='POSTED' WHERE id=%s", (j["id"],))
    assert "FIN_UNBALANCED_JOURNAL" in str(e.value)


def test_003_closed_period_rejected(conn, make_entity):
    ctx, a = make_entity()
    july = periods.period_for(conn, ctx.entity_id, D)
    # close Jan..Jul in order (empty periods pass the checklist)
    for p in q(conn, "SELECT id FROM fin_periods WHERE legal_entity_id=%s AND start_date <= %s ORDER BY start_date",
               (ctx.entity_id, july["start_date"])):
        periods.close_period(conn, ctx, p["id"])
    j = posting.create_manual(conn, ctx, journal_date=D, description="Late", lines=_jv(a, "10100", "40000"))
    with pytest.raises(FinError) as e:
        posting.post_manual(conn, ctx, j["id"])
    assert e.value.code == "PERIOD_CLOSED"
    assert not q(conn, "SELECT 1 FROM fin_v_general_ledger WHERE journal_id=%s", (j["id"],))


def test_004_inactive_account_rejected(conn, make_entity):
    ctx, a = make_entity()
    accounts.set_status(conn, ctx, a["62200"]["id"], active=False, reason="test")
    with pytest.raises(FinError) as e:
        posting.create_manual(conn, ctx, journal_date=D, description="x", lines=_jv(a, "62200", "10100"))
    assert e.value.code == "ACCOUNT_INACTIVE"


def test_005_idempotent_system_posting_never_creates_two_journals(conn, make_entity):
    ctx, a = make_entity()
    kw = dict(event_type="TEST_EVENT", journal_date=D, lines=_jv(a, "10290", "40000"), description="once",
              source_type="test", source_id="abc", idempotency_key="IDEM-1")
    j1 = posting.post_system(conn, ctx, **kw)
    j2 = posting.post_system(conn, ctx, **kw)
    assert j1["id"] == j2["id"]
    assert q1(conn, "SELECT COUNT(*) n FROM fin_journals WHERE legal_entity_id=%s", (ctx.entity_id,))["n"] == 1


def test_006_reversal_keeps_original_intact(conn, make_entity):
    ctx, a = make_entity()
    j = posting.post_manual(conn, ctx, posting.create_manual(conn, ctx, journal_date=D, description="orig",
                                                             lines=_jv(a, "10100", "40000"))["id"])
    rev = posting.reverse(conn, ctx, j["id"], reason="posted in error")
    orig = posting.get_journal(conn, ctx.entity_id, j["id"])
    assert orig["status"] == "REVERSED" and str(orig["reversed_by_id"]) == str(rev["id"])
    assert str(rev["reversal_of_id"]) == str(j["id"]) and rev["journal_type"] == "REVERSAL"
    assert [str(l["debit"]) for l in orig["lines"]] == ["100000.00", "0.00"]  # untouched
    bal = ledger.account_balance(conn, ctx.entity_id, a["10100"]["id"], D)
    assert str(bal) == "0.00"
    with pytest.raises(FinError) as e:
        posting.reverse(conn, ctx, j["id"], reason="again")
    assert e.value.code == "TRANSACTION_ALREADY_POSTED"


def test_006b_posted_journal_is_immutable_in_the_database(conn, make_entity):
    ctx, a = make_entity()
    j = posting.post_manual(conn, ctx, posting.create_manual(conn, ctx, journal_date=D, description="orig",
                                                             lines=_jv(a, "10100", "40000"))["id"])
    for sql in ("UPDATE fin_journal_lines SET debit=1, base_debit=1 WHERE journal_id=%s AND debit>0",
                "DELETE FROM fin_journal_lines WHERE journal_id=%s",
                "UPDATE fin_journals SET description='edited' WHERE id=%s"):
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT s")
            with pytest.raises(psycopg2.Error) as e:
                cur.execute(sql, (j["id"],))
            cur.execute("ROLLBACK TO SAVEPOINT s")
        assert "FIN_POSTED_IMMUTABLE" in str(e.value)


def test_007_gl_integrity_after_many_postings(conn, make_entity):
    ctx, a = make_entity()
    for i, (dr, cr) in enumerate([("10100", "40000"), ("10290", "11000"), ("50000", "12000"), ("62200", "10290")]):
        posting.post_system(conn, ctx, event_type="T", journal_date=D, lines=_jv(a, dr, cr, 1000 * (i + 1)),
                            description="t", source_type="t", source_id=i)
    r = q1(conn, "SELECT SUM(debit) d, SUM(credit) c FROM fin_v_general_ledger WHERE legal_entity_id=%s", (ctx.entity_id,))
    assert r["d"] == r["c"] == 10000


def test_008_trial_balance_balances(conn, make_entity):
    ctx, a = make_entity()
    posting.post_system(conn, ctx, event_type="T", journal_date=dt.date(2026, 3, 1), lines=[
        {"account_id": a["11000"]["id"], "debit": 110000},
        {"account_id": a["40000"]["id"], "credit": 100000},
        {"account_id": a["40800"]["id"], "credit": 10000}], description="invoice", source_type="t", source_id=1)
    tb = ledger.trial_balance(conn, ctx.entity_id, dt.date(2026, 3, 1), dt.date(2026, 3, 31))
    assert tb["balanced"] and tb["difference"] == 0
    assert {r["code"] for r in tb["rows"]} == {"11000", "40000", "40800"}


def test_009_entity_isolation(conn, make_entity):
    ctx_a, a = make_entity()
    ctx_b, b = make_entity()
    with pytest.raises(FinError) as e:
        accounts.get_account(conn, ctx_b.entity_id, a["10100"]["id"])
    assert e.value.code == "RESOURCE_NOT_FOUND"
    # posting B's journal against A's account is refused as not found in this company
    with pytest.raises(FinError) as e:
        posting.create_manual(conn, ctx_b, journal_date=D, description="x",
                              lines=[{"account_id": a["10100"]["id"], "debit": 5}, {"account_id": b["40000"]["id"], "credit": 5}])
    assert e.value.code == "RESOURCE_NOT_FOUND"


def test_010_audit_trail_in_order(conn, make_entity):
    ctx, a = make_entity()
    acct = accounts.create_account(conn, ctx, {"code": "70000", "name": "Advertising", "subtype": "OPERATING_EXPENSE"})
    accounts.set_status(conn, ctx, acct["id"], active=False)
    accounts.set_status(conn, ctx, acct["id"], active=True)
    j = posting.create_manual(conn, ctx, journal_date=D, description="ads", lines=[
        {"account_id": acct["id"], "debit": 500}, {"account_id": a["10290"]["id"], "credit": 500}])
    posting.submit(conn, ctx, j["id"])
    checker = type(ctx)("checker", "checker", ["admin"], ctx.entity_id, {"*"}, "t")
    posting.approve(conn, checker, j["id"])
    posting.post_manual(conn, ctx, j["id"])
    posting.reverse(conn, ctx, j["id"], reason="wrong period")
    acts = [r["action"] for r in q(conn, """SELECT action FROM fin_audit_events WHERE legal_entity_id=%s
                                            AND action NOT IN ('FISCAL_YEAR_CREATED') AND
                                            (entity_id=%s OR entity_id=%s) ORDER BY id""",
                                   (ctx.entity_id, str(acct["id"]), str(j["id"])))]
    assert acts == ["ACCOUNT_CREATED", "ACCOUNT_DEACTIVATED", "ACCOUNT_ACTIVATED", "JOURNAL_CREATED",
                    "JOURNAL_SUBMITTED", "JOURNAL_APPROVED", "JOURNAL_POSTED", "JOURNAL_REVERSED"]
    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM fin_audit_events WHERE legal_entity_id=%s", (ctx.entity_id,))


def test_maker_checker_blocks_self_approval(conn, make_entity):
    ctx, a = make_entity()
    j = posting.create_manual(conn, ctx, journal_date=D, description="x", lines=_jv(a, "10100", "40000"))
    posting.submit(conn, ctx, j["id"])
    with pytest.raises(FinError) as e:
        posting.approve(conn, ctx, j["id"])
    assert e.value.code == "PERMISSION_DENIED"


def test_control_account_needs_permission_for_manual_journal(conn, make_entity, ctx_for):
    ctx, a = make_entity()
    clerk = ctx_for(ctx.entity_id, "clerk", perms=("accounting.journal.create",))
    with pytest.raises(FinError) as e:
        posting.create_manual(conn, clerk, journal_date=D, description="x", lines=_jv(a, "11000", "40000"))
    assert e.value.code == "CONTROL_ACCOUNT"
