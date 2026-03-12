import os
import json
import time
import asyncio
import uuid
import datetime as dt
from typing import Set
from src.db import db, audit_event

LEDGER_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'event_ledger.jsonl')


class AgentSubscriptionProcessor:
    def __init__(self):
        self._processed: Set[str] = set()
        self._ensure_ledger()

    def _ensure_ledger(self):
        parent = os.path.dirname(LEDGER_PATH)
        if not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(LEDGER_PATH):
            open(LEDGER_PATH, 'a').close()

    def _read_ledger(self):
        out = []
        try:
            with open(LEDGER_PATH, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            return []
        return out

    def _should_create_thread(self, ev: dict) -> bool:
        # Simple heuristics: create threads for inventory movements, delivery status changes, and document approvals
        dept = (ev.get('department') or '').lower()
        et = (ev.get('event_type') or '').lower()
        if dept == 'inventory' and 'movement' in et:
            return True
        if dept == 'logistics' and 'deliverystatus' in et.lower():
            return True
        if dept == 'documents' and ('approval' in et or 'uploaded' in et):
            return True
        return False

    def _build_thread_payload(self, ev: dict) -> dict:
        title = f"{ev.get('department')}: {ev.get('event_type')}"
        payload = ev.get('payload') or {}
        body = json.dumps(payload, indent=2, default=str)
        message = f"Event {ev.get('event_id') or ev.get('version_hash')}:\n{body}"
        return {'title': title, 'message': message}

    def _mark_processed(self, ev_id: str):
        self._processed.add(ev_id)

    async def run_loop(self, interval: int = 5):
        while True:
            try:
                ledger = self._read_ledger()
                for ev in ledger:
                    ev_id = ev.get('event_id') or ev.get('version_hash')
                    if not ev_id or ev_id in self._processed:
                        continue
                    if self._should_create_thread(ev):
                        try:
                            payload = self._build_thread_payload(ev)
                            thread_id = str(uuid.uuid4())
                            thread_record = {
                                'id': thread_id,
                                'title': payload['title'],
                                'created_by': None,
                                'created_at': dt.datetime.utcnow().isoformat() + 'Z',
                                'last_activity_at': dt.datetime.utcnow().isoformat() + 'Z'
                            }
                            db.table('threads').insert(thread_record).execute()
                            # initial message
                            msg = {
                                'id': str(uuid.uuid4()),
                                'thread_id': thread_id,
                                'sender': None,
                                'content': payload['message'],
                                'created_at': dt.datetime.utcnow().isoformat() + 'Z',
                                'metadata': {'event_id': ev_id}
                            }
                            db.table('thread_messages').insert(msg).execute()
                            audit_event('agent_thread_created', {'event_id': ev_id, 'thread_id': thread_id}, actor_id=None, event_class='agents', action='create_thread', subject_type='thread', subject_id=thread_id)
                        except Exception:
                            pass
                    self._mark_processed(ev_id)
            except Exception:
                pass
            await asyncio.sleep(interval)


processor = AgentSubscriptionProcessor()


def start_processor(loop, interval: int = 5):
    try:
        loop.create_task(processor.run_loop(interval=interval))
    except Exception:
        pass
