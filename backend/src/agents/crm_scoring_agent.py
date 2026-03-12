import threading
import time
import logging
from typing import Dict

import src.db as db

logger = logging.getLogger(__name__)


class CRMScoringAgent:
    """Updates customer scores based on recent events and KPIs.

    This agent watches for events and recalculates a simple score stored
    on `customers.score`.
    """

    def __init__(self, poll_interval: int = 30):
        self.poll_interval = poll_interval
        self._running = False

    def compute_score(self, customer_id: int, events: list, kpis: list) -> float:
        # Very small heuristic: base score 50, + recent activity, - risk signals
        score = 50.0
        activity_bonus = min(20.0, len([e for e in events if e.get('type') == 'activity']) * 2.0)
        risk_penalty = 0.0
        rs = next((k for k in kpis if k.get('metric') == f'risk.customer.{customer_id}'), None)
        if rs:
            risk_penalty = float(rs.get('value', 0))
        score = score + activity_bonus - risk_penalty
        return max(0.0, min(100.0, round(score, 1)))

    def fetch_customer_events(self, customer_id: int):
        try:
            res = db.table('event_ledger').select('*').eq('linked_customer_id', customer_id).execute()
            return res.data or []
        except Exception:
            logger.exception('Failed fetching events for customer %s', customer_id)
            return []

    def fetch_kpis(self):
        try:
            res = db.table('placeware_kpis').select('*').execute()
            return res.data or []
        except Exception:
            logger.exception('Failed fetching KPIs')
            return []

    def upsert_customer_score(self, customer_id: int, score: float):
        try:
            db.table('customers').update({'score': score}).eq('id', customer_id).execute()
        except Exception:
            logger.exception('Failed upserting customer score for %s', customer_id)

    def tick(self):
        # Simple loop: fetch recent customers with activity (limited to 50)
        try:
            res = db.table('customers').select('id').limit(50).execute()
            customers = res.data or []
            kpis = self.fetch_kpis()
            for c in customers:
                cid = c.get('id')
                events = self.fetch_customer_events(cid)
                score = self.compute_score(cid, events, kpis)
                logger.info('Updating customer %s score=%s', cid, score)
                self.upsert_customer_score(cid, score)
        except Exception:
            logger.exception('CRMScoringAgent tick failed')

    def run(self):
        self._running = True
        while self._running:
            self.tick()
            time.sleep(self.poll_interval)

    def stop(self):
        self._running = False


def start_in_thread(poll_interval: int = 30):
    agent = CRMScoringAgent(poll_interval=poll_interval)
    t = threading.Thread(target=agent.run, daemon=True)
    t.start()
    return agent
