"""Risk Agent skeleton.

Listens to `event_bus` and evaluates simple risk signals, storing alerts
in `placeware_kpis` under key `risk_signals` and logging to audit via db.
"""
import os
import json
import logging
import threading

try:
    import psycopg2
except Exception:
    psycopg2 = None

from ..db import db

LOG = logging.getLogger(__name__)


class RiskAgent:
    def __init__(self, dsn: str | None = None, channel: str = 'event_bus'):
        self.dsn = dsn or os.getenv('DATABASE_URL')
        self.channel = channel
        self.conn = None

    def connect(self):
        if psycopg2 is None:
            LOG.warning('psycopg2 not installed; RiskAgent will not run')
            return
        self.conn = psycopg2.connect(self.dsn)
        self.conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = self.conn.cursor()
        cur.execute(f"LISTEN {self.channel};")
        LOG.info('RiskAgent listening on %s', self.channel)

    def _now(self):
        import datetime

        return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    def handle(self, payload_text: str):
        try:
            payload = json.loads(payload_text)
        except Exception:
            payload = {'raw': payload_text}
        ev_type = payload.get('event_type')
        LOG.info('RiskAgent processing event: %s', ev_type)

        # Simple heuristic: if payload contains fields that indicate risk, increment risk_signals
        risk_flag = False
        pl = payload.get('payload') or {}
        if isinstance(pl, dict):
            # e.g., presence of 'risk_score' or 'risk' keys
            if pl.get('risk_score') and float(pl.get('risk_score') or 0) > 10:
                risk_flag = True
            if pl.get('approval_status') == 'pending' and ev_type in ('lead_created', 'opportunity_created'):
                risk_flag = True

        if risk_flag:
            try:
                resp = db.table('placeware_kpis').select('metric_value').eq('metric_key', 'risk_signals').limit(1).execute()
                rows = resp.data or []
                if rows:
                    new = float(rows[0].get('metric_value', 0)) + 1
                    db.table('placeware_kpis').update({'metric_value': new, 'updated_at': self._now()}).eq('metric_key', 'risk_signals').execute()
                else:
                    db.table('placeware_kpis').insert({'metric_key': 'risk_signals', 'metric_value': 1, 'updated_at': self._now()}).execute()
            except Exception as e:
                LOG.debug('RiskAgent failed to update KPI: %s', e)

    def run(self):
        if psycopg2 is None:
            LOG.warning('psycopg2 not available; RiskAgent exiting')
            return
        self.connect()
        cur = self.conn.cursor()
        try:
            import select
            while True:
                if select.select([self.conn], [], [], 5) == ([], [], []):
                    continue
                self.conn.poll()
                while self.conn.notifies:
                    notify = self.conn.notifies.pop(0)
                    self.handle(notify.payload)
        except Exception as e:
            LOG.exception('RiskAgent encountered error: %s', e)
        finally:
            try:
                cur.close()
                self.conn.close()
            except Exception:
                pass


def start_in_thread(dsn: str | None = None):
    agent = RiskAgent(dsn=dsn)
    t = threading.Thread(target=agent.run, daemon=True)
    t.start()
    return t
