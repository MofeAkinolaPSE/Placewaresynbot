"""Turn a typed sentence into a task draft.

    "Remind me to call Skylark every Monday at 10am"
        -> reminder · "Call Skylark" · repeats weekly on Monday · first Mon 10:00
    "Ask Tayo to send the September timesheets by Friday, urgent"
        -> task for Tayo · "Send the September timesheets" · due Fri 17:00 · critical
    "Note: Vaccines Place reorder coming in on 12 Oct"
        -> note · "Vaccines Place reorder coming in" · 12 Oct

Deterministic (no AI call): the same words always give the same draft, it works
offline, and the person sees exactly what was understood before anything is saved.
Dates are Lagos time; a bare date means end of the working day (17:00) for tasks
and 09:00 for reminders.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Tuple

from src.services.staff_workspace import DEPARTMENTS, TZ, now, people
from src.fin.db import tx

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WD_ABBR = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}
WD_CODE = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_DAY = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed|thur?s?|fri|sat|sun)"
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_TIME = r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\bat\s+(\d{1,2})(?::(\d{2}))?\b|\b(\d{1,2}):(\d{2})\b|\b(noon|midday|midnight)\b"


def _wd(s: str) -> int:
    s = s.lower()
    return WEEKDAYS.index(s) if s in WEEKDAYS else WD_ABBR[s[:4] if s[:4] in WD_ABBR else s[:3]]


class _Text:
    """The sentence, with understood phrases cut out as they are consumed."""

    def __init__(self, s: str):
        self.s = " " + s + " "

    def take(self, pattern: str, flags=re.I) -> Optional[re.Match]:
        m = re.search(pattern, self.s, flags)
        if m:
            self.s = self.s[:m.start()] + " " + self.s[m.end():]
        return m

    def peek(self, pattern: str, flags=re.I) -> Optional[re.Match]:
        return re.search(pattern, self.s, flags)


def _next_weekday(base: dt.date, wd: int, strictly_after: bool = False) -> dt.date:
    delta = (wd - base.weekday()) % 7
    if delta == 0 and strictly_after:
        delta = 7
    return base + dt.timedelta(days=delta)


def _parse_time(t: _Text) -> Optional[dt.time]:
    m = t.take(r"\b(?:at\s+)?(noon|midday|midnight)\b")
    if m:
        return dt.time(12, 0) if m.group(1).lower() in ("noon", "midday") else dt.time(0, 0)
    m = t.take(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b")
    if m:
        h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
        return dt.time(h + (12 if m.group(3).lower() == "pm" else 0), mi)
    m = t.take(r"\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b")
    if m:
        return dt.time(int(m.group(1)), int(m.group(2)))
    m = t.take(r"\bat\s+(\d{1,2})\b(?!\s*(?:days?|weeks?|hours?|mins?|minutes?|/))")
    if m:
        h = int(m.group(1))
        return dt.time(h + 12 if 1 <= h <= 6 else h % 24, 0)   # "at 3" in a work context means 3pm
    for word, hh in (("first thing", 8), ("this morning", 9), ("in the morning", 9), ("morning", 9), ("lunchtime", 12),
                     ("this afternoon", 14), ("in the afternoon", 14), ("afternoon", 14), ("this evening", 18),
                     ("in the evening", 18), ("evening", 18), ("tonight", 20)):
        if t.take(rf"\b{word}\b"):
            return dt.time(hh, 0)
    return None


def _parse_recurrence(t: _Text) -> Tuple[Optional[str], Optional[str], Optional[dt.date]]:
    """Returns (rule, label, until)."""
    until = None
    m = t.take(rf"\buntil\s+(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON}\b|\buntil\s+{_MON}\s+(\d{{1,2}})\b|\buntil\s+(\d{{4}}-\d{{2}}-\d{{2}})")
    if m:
        today = now().astimezone(TZ).date()
        if m.group(5):
            until = dt.date.fromisoformat(m.group(5))
        else:
            day = int(m.group(1) or m.group(4))
            mon = MONTHS.index((m.group(2) or m.group(3))[:3].lower()) + 1
            until = dt.date(today.year, mon, day)
            if until < today:
                until = dt.date(today.year + 1, mon, day)
    if t.take(r"\b(every\s+weekday|every\s+working\s+day|on\s+weekdays|weekdays)\b"):
        return "weekdays", "every weekday", until
    if t.take(r"\b(every\s+day|daily|each\s+day)\b"):
        return "daily", "every day", until
    m = t.take(r"\bevery\s+(\d+|two|three|four|other)\s+(day|week|month)s?\b|\bevery\s+other\s+(day|week|month)\b")
    if m:
        n = {"two": 2, "three": 3, "four": 4, "other": 2}.get((m.group(1) or "other").lower(), None) or int(m.group(1))
        unit = (m.group(2) or m.group(3)).lower()
        if unit == "month":
            return f"every:{n}:months", f"every {n} months", until
        return f"every:{n}:{unit}s", f"every {n} {unit}s", until
    m = t.take(rf"\bevery\s+({_DAY}(?:\s*(?:,|and|&)\s*{_DAY})*)\b")
    if m:
        days = sorted({_wd(d) for d in re.findall(_DAY, m.group(1), re.I)})
        return f"weekly:{','.join(WD_CODE[d] for d in days)}", "every " + ", ".join(WEEKDAYS[d].capitalize() for d in days), until
    m = t.take(r"\b(?:on\s+the\s+)?(\d{1,2})(?:st|nd|rd|th)\s+of\s+(?:every|each)\s+month\b|\b(?:every|each)\s+month\s+on\s+the\s+(\d{1,2})(?:st|nd|rd|th)?\b")
    if m:
        d = int(m.group(1) or m.group(2))
        return f"monthly:{d}", f"monthly on the {d}{'st' if d in (1, 21, 31) else 'nd' if d in (2, 22) else 'rd' if d in (3, 23) else 'th'}", until
    if t.take(r"\b(?:at\s+the\s+)?end\s+of\s+(?:every|each)\s+month\b|\bevery\s+month\s+end\b|\bmonth[- ]end\b"):
        return "monthly:last", "at the end of every month", until
    if t.take(r"\b(every\s+month|monthly|each\s+month)\b"):
        return "monthly", "every month", until
    if t.take(r"\b(every\s+week|weekly|each\s+week)\b"):
        return "weekly", "every week", until
    return None, None, until


def _parse_date(t: _Text, today: dt.date) -> Tuple[Optional[dt.date], Optional[dt.time], Optional[dt.datetime]]:
    """(date, implied time, exact datetime for 'in 2 hours')."""
    m = t.take(r"\bin\s+(\d+|an?|one|two|three|half\s+an?)\s+(minute|min|hour|hr|day|week)s?\b")
    if m:
        raw = m.group(1).lower()
        n = 0.5 if raw.startswith("half") else {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}.get(raw) or int(raw)
        unit = m.group(2).lower()
        if unit in ("minute", "min"):
            return None, None, now() + dt.timedelta(minutes=n)
        if unit in ("hour", "hr"):
            return None, None, now() + dt.timedelta(hours=n)
        return today + dt.timedelta(days=int(n) * (7 if unit == "week" else 1)), None, None
    if t.take(r"\b(?:by\s+)?(?:end\s+of\s+(?:the\s+)?day|eod|close\s+of\s+business|cob)\b"):
        return today, dt.time(17, 0), None
    if t.take(r"\b(?:by\s+)?(?:end\s+of\s+(?:the\s+)?week|eow)\b"):
        return _next_weekday(today, 4), dt.time(17, 0), None
    if t.take(r"\b(?:by\s+)?end\s+of\s+(?:the\s+)?month\b"):
        nxt = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return nxt - dt.timedelta(days=1), dt.time(17, 0), None
    if t.take(r"\b(?:the\s+)?day\s+after\s+tomorrow\b"):
        return today + dt.timedelta(days=2), None, None
    if t.take(r"\b(?:by\s+|on\s+)?tomorrow\b|\btmrw?\b|\btmr\b"):
        return today + dt.timedelta(days=1), None, None
    if t.take(r"\btonight\b"):
        return today, dt.time(20, 0), None
    if t.take(r"\b(?:by\s+|for\s+)?today\b"):
        return today, None, None
    if t.take(r"\bnext\s+week\b"):
        return _next_weekday(today, 0, strictly_after=True), dt.time(9, 0), None
    if t.take(r"\bnext\s+month\b"):
        return (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1), dt.time(9, 0), None
    m = t.take(rf"\b(?:by\s+|on\s+|this\s+|next\s+)?{_DAY}\b")
    if m:
        # "Friday" = the coming Friday (today if it is Friday); "next Friday" = the coming one, never today
        return _next_weekday(today, _wd(m.group(1)), strictly_after="next" in m.group(0).lower()), None, None
    m = t.take(r"\b(\d{4})-(\d{2})-(\d{2})\b")
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), None, None
    m = t.take(rf"\b(?:by\s+|on\s+)?(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}\b|\b(?:by\s+|on\s+)?{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b")
    if m:
        day = int(m.group(1) or m.group(4))
        mon = MONTHS.index((m.group(2) or m.group(3))[:3].lower()) + 1
        d = dt.date(today.year, mon, day)
        return (d if d >= today else dt.date(today.year + 1, mon, day)), None, None
    m = t.take(r"\b(?:by\s+|on\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")     # day/month, as written in Nigeria
    if m:
        day, mon = int(m.group(1)), int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else today.year
        yr = yr + 2000 if yr < 100 else yr
        try:
            d = dt.date(yr, mon, day)
        except ValueError:
            return None, None, None
        return (d if d >= today or m.group(3) else dt.date(yr + 1, mon, day)), None, None
    return None, None, None


def _first_occurrence(rule: str, today: dt.date) -> dt.date:
    if rule.startswith("weekly:"):
        days = [WD_CODE.index(c) for c in rule.split(":")[1].split(",")]
        return min(_next_weekday(today, d) for d in days)
    if rule == "weekdays":
        return today if today.weekday() < 5 else _next_weekday(today, 0)
    if rule.startswith("monthly:"):
        arg = rule.split(":")[1]
        if arg == "last":
            nxt = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            return nxt - dt.timedelta(days=1)
        d = int(arg)
        try:
            c = today.replace(day=d)
        except ValueError:
            c = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        return c if c >= today else (c.replace(day=1) + dt.timedelta(days=32)).replace(day=min(d, 28))
    return today


def parse(text: str, user: Dict[str, Any]) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Type what needs doing")
    me = str(user.get("sub") or "")
    t = _Text(raw)
    understood: List[str] = []
    today = now().astimezone(TZ).date()

    # kind
    kind = "task"
    if t.take(r"^\s*(?:please\s+)?remind\s+me\s+(?:to\s+|about\s+|that\s+)?"):
        kind = "reminder"
    elif t.take(r"^\s*(?:reminder|remind)\s*[:\-]\s*"):
        kind = "reminder"
    elif t.take(r"^\s*(?:note|fyi|n\.b\.?|nb)\s*[:\-]\s*|^\s*note\s+(?:that\s+)?"):
        kind = "note"
    elif t.take(r"^\s*(?:todo|to\s*do|task)\s*[:\-]\s*"):
        kind = "task"

    # who it is for
    with tx() as conn:
        team = [p for p in people(conn) if p["user_id"]]
    def match_person(word: str) -> Optional[Dict[str, Any]]:
        w = word.lower().strip(".,")
        for p in team:
            first = p["name"].split()[0].lower()
            if w in (first, p["name"].lower(), (p["email"] or "").split("@")[0].lower()):
                return p
        return None
    assignee = None
    m = t.peek(r"@([A-Za-z][\w.-]+)")
    if m and match_person(m.group(1)):
        assignee = match_person(m.group(1)); t.take(re.escape(m.group(0)))
    if not assignee:
        m = t.peek(r"^\s*(?:ask|tell|get|have)\s+([A-Za-z][\w.-]+)\s+(?:to\s+)?")
        if m and match_person(m.group(1)):
            assignee = match_person(m.group(1)); t.take(r"^\s*(?:ask|tell|get|have)\s+[A-Za-z][\w.-]+\s+(?:to\s+)?")
    if not assignee:
        m = t.peek(r"\b(?:assign(?:ed)?\s+to|for)\s+([A-Za-z][\w.-]+)\b")
        if m and match_person(m.group(1)):
            assignee = match_person(m.group(1)); t.take(r"\b(?:assign(?:ed)?\s+to|for)\s+" + re.escape(m.group(1)) + r"\b")
    if assignee and assignee["user_id"] == me:
        assignee = None
    if assignee:
        understood.append(f"for {assignee['name']}")

    # priority
    priority = "medium"
    if t.take(r"\b(urgent(?:ly)?|asap|a\.s\.a\.p|critical|immediately|right\s+away)\b|!!+"):
        priority = "critical"
    elif t.take(r"\b(high\s+priority|important|priority)\b|(?<!\w)!(?!\w)"):
        priority = "high"
    elif t.take(r"\b(low\s+priority|no\s+rush|whenever|when\s+you\s+can)\b"):
        priority = "low"
    if priority != "medium":
        understood.append(f"{priority} priority")

    # repeat, date, time
    rule, rule_label, until = _parse_recurrence(t)
    d, implied_time, exact = _parse_date(t, today)
    tm = _parse_time(t) or implied_time
    due: Optional[dt.datetime] = exact
    if not due:
        if rule and not d:
            d = _first_occurrence(rule, today)
        if d or tm:
            default_time = dt.time(9, 0) if kind == "reminder" or rule else dt.time(17, 0)
            d = d or today
            due = dt.datetime.combine(d, tm or default_time, TZ)
            if due < now() and not (d and d > today):
                # "at 9am" said after 9am means tomorrow; a repeating one starts at its next occurrence
                due += dt.timedelta(days=1)
    if rule:
        understood.append(f"repeats {rule_label}" + (f" until {until:%d %b}" if until else ""))
    if due:
        understood.append(f"{'remind' if kind == 'reminder' else 'due'} {due.astimezone(TZ):%a %d %b %H:%M}")

    # department mentioned
    dept = None
    for dname in DEPARTMENTS:
        if re.search(rf"\b{dname}\b", t.s, re.I) and dname not in ("Admin",):
            dept = dname
            break

    # what is left is the title
    title = re.sub(r"\s+", " ", t.s).strip(" ,.;:-")
    title = re.sub(r"^(?:to|and|please|pls)\s+", "", title, flags=re.I)
    title = re.sub(r"\s+(?:by|on|at|for|to|and|,)$", "", title, flags=re.I).strip(" ,.;:-")
    title = re.sub(r"\s+,", ",", title)
    if not title:
        title = raw
    title = title[0].upper() + title[1:]
    if kind == "reminder" and not due:
        due = dt.datetime.combine(today + dt.timedelta(days=1), dt.time(9, 0), TZ)
        understood.append(f"remind {due:%a %d %b %H:%M} (no time given)")
    return {
        "title": title[:300], "kind": kind, "priority": priority,
        "due_at": due.isoformat() if due else None,
        "assigned_to": assignee["user_id"] if assignee else None, "assignee_name": assignee["name"] if assignee else None,
        "department": dept, "recurrence": rule, "recurrence_label": rule_label, "recurrence_until": until.isoformat() if until else None,
        "understood": [f"{kind}"] + understood, "text": raw,
    }
