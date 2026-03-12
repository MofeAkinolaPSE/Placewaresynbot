import threading
import time
import logging

logger = logging.getLogger(__name__)
import src.db as db


class LogisticsAgent:
    """Placeholder logistics agent that suggests simple route aggregations.

    This agent is a scaffold for route optimization and will expose a
    periodic summary metric `logistics.pending_routes`.
    """

    def __init__(self, poll_interval: int = 60):
        self.poll_interval = poll_interval
        self._running = False

    def compute_pending_routes(self, events: list) -> int:
        return len([e for e in events if e.get('event_type') == 'delivery' and e.get('payload', {}).get('status') != 'delivered'])

    def fetch_delivery_events(self):
        try:
            res = db.db.table('event_ledger').select('*').execute()
            return res.data or []
        except Exception:
            logger.exception('Failed fetching delivery events')
            return []

    def upsert_metric(self, count: int):
        try:
            db.db.table('placeware_kpis').upsert({'metric': 'logistics.pending_routes', 'value': count}).execute()
        except Exception:
            logger.exception('Failed writing logistics metric')

    def tick(self):
        events = self.fetch_delivery_events()
        pending = self.compute_pending_routes(events)
        logger.info('Logistics pending routes=%s', pending)
        self.upsert_metric(pending)

    def run(self):
        self._running = True
        while self._running:
            self.tick()
            time.sleep(self.poll_interval)

    def stop(self):
        self._running = False


def start_in_thread(poll_interval: int = 60):
    agent = LogisticsAgent(poll_interval=poll_interval)
    import threading as _t
    t = _t.Thread(target=agent.run, daemon=True)
    t.start()
    return agent
