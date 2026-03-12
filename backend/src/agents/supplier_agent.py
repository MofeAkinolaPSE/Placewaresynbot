import threading
import time
import logging

import src.db as db

logger = logging.getLogger(__name__)


class SupplierAgent:
    """Calculates supplier reliability and updates supplier records.

    Uses simple heuristics: on-time deliveries vs delays to compute a
    reliability_score between 0 and 100.
    """

    def __init__(self, poll_interval: int = 60):
        self.poll_interval = poll_interval
        self._running = False

    def compute_reliability(self, supplier_id: int, events: list) -> float:
        total = len(events)
        if total == 0:
            return 75.0
        on_time = len([e for e in events if e.get('payload', {}).get('status') == 'delivered'])
        delayed = len([e for e in events if e.get('payload', {}).get('status') == 'delayed'])
        score = 50 + (on_time - delayed) * 5
        return max(0.0, min(100.0, float(score)))

    def fetch_supplier_events(self, supplier_id: int):
        try:
            res = db.db.table('event_ledger').select('*').eq('linked_supplier_id', supplier_id).execute()
            return res.data or []
        except Exception:
            logger.exception('Failed fetching supplier events')
            return []

    def upsert_supplier_score(self, supplier_id: int, score: float):
        try:
            db.db.table('suppliers').update({'reliability_score': score}).eq('id', supplier_id).execute()
        except Exception:
            logger.exception('Failed updating supplier score %s', supplier_id)

    def tick(self):
        try:
            res = db.db.table('suppliers').select('id').execute()
            suppliers = res.data or []
            for s in suppliers:
                sid = s.get('id')
                events = self.fetch_supplier_events(sid)
                score = self.compute_reliability(sid, events)
                logger.info('Supplier %s reliability=%s', sid, score)
                self.upsert_supplier_score(sid, score)
        except Exception:
            logger.exception('SupplierAgent tick failed')

    def run(self):
        self._running = True
        while self._running:
            self.tick()
            time.sleep(self.poll_interval)

    def stop(self):
        self._running = False


def start_in_thread(poll_interval: int = 60):
    agent = SupplierAgent(poll_interval=poll_interval)
    import threading as _t
    t = _t.Thread(target=agent.run, daemon=True)
    t.start()
    return agent
