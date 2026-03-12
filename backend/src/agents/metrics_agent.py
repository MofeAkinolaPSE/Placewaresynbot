"""Simple Metrics Agent skeleton.

Listens for Event Bus notifications and recalculates lightweight KPIs
into a `placeware_kpis` supabase table (or logs if not available).
"""
import os
import json
import logging
import threading
import datetime

try:
    import psycopg2
except Exception:
    psycopg2 = None

from ..db import db

LOG = logging.getLogger(__name__)


class MetricsAgent:
    def __init__(self, dsn: str | None = None, channel: str = 'event_bus'):
        self.dsn = dsn or os.getenv('DATABASE_URL')
        self.channel = channel
        self.conn = None

    def connect(self):
        if psycopg2 is None:
            LOG.warning('psycopg2 not installed; MetricsAgent will not run')
            return
        self.conn = psycopg2.connect(self.dsn)
        self.conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = self.conn.cursor()
        cur.execute(f"LISTEN {self.channel};")
        LOG.info('MetricsAgent listening on %s', self.channel)

    def _now(self):
        return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    def _inc_lead_campaign(self, campaign_id):
        if not campaign_id:
            return
        try:
            resp = db.table('placeware_kpi_leads_by_campaign').select('lead_count').eq('campaign_id', campaign_id).limit(1).execute()
            rows = resp.data or []
            if rows:
                new = int(rows[0].get('lead_count', 0)) + 1
                db.table('placeware_kpi_leads_by_campaign').update({'lead_count': new, 'updated_at': self._now()}).eq('campaign_id', campaign_id).execute()
            else:
                db.table('placeware_kpi_leads_by_campaign').insert({'campaign_id': campaign_id, 'lead_count': 1, 'updated_at': self._now()}).execute()
        except Exception as e:
            LOG.debug('Failed increment campaign KPI: %s', e)

    def _inc_lead_source(self, source):
        if not source:
            return
        try:
            resp = db.table('placeware_kpi_leads_by_source').select('lead_count').eq('source', source).limit(1).execute()
            rows = resp.data or []
            if rows:
                new = int(rows[0].get('lead_count', 0)) + 1
                db.table('placeware_kpi_leads_by_source').update({'lead_count': new, 'updated_at': self._now()}).eq('source', source).execute()
            else:
                db.table('placeware_kpi_leads_by_source').insert({'source': source, 'lead_count': 1, 'updated_at': self._now()}).execute()
        except Exception as e:
            LOG.debug('Failed increment lead source KPI: %s', e)

    def _inc_opportunity_stage(self, stage, value):
        if not stage:
            return
        try:
            resp = db.table('placeware_kpi_opportunities_by_stage').select('opp_count', 'total_value').eq('stage', stage).limit(1).execute()
            rows = resp.data or []
            if rows:
                new_count = int(rows[0].get('opp_count', 0)) + 1
                new_value = float(rows[0].get('total_value') or 0) + float(value or 0)
                db.table('placeware_kpi_opportunities_by_stage').update({'opp_count': new_count, 'total_value': new_value, 'updated_at': self._now()}).eq('stage', stage).execute()
            else:
                db.table('placeware_kpi_opportunities_by_stage').insert({'stage': stage, 'opp_count': 1, 'total_value': float(value or 0), 'updated_at': self._now()}).execute()
        except Exception as e:
            LOG.debug('Failed increment opportunity KPI: %s', e)

    def handle(self, payload_text: str):
        try:
            payload = json.loads(payload_text)
        except Exception:
            payload = {'raw': payload_text}
        ev_type = payload.get('event_type')
        LOG.info('MetricsAgent processing event: %s', ev_type)

        if ev_type == 'lead_created':
            lead = payload.get('payload', {}).get('lead') or {}
            campaign = lead.get('linked_campaign_id')
            source = lead.get('source') or (lead.get('metadata') or {}).get('source')
            self._inc_lead_campaign(campaign)
            self._inc_lead_source(source)

        if ev_type == 'opportunity_created':
            opp = payload.get('payload', {}).get('opportunity') or {}
            stage = opp.get('status') or (opp.get('metadata') or {}).get('stage') or 'unknown'
            value = opp.get('value') or (opp.get('metadata') or {}).get('value') or 0
            try:
                value_num = float(value or 0)
            except Exception:
                value_num = 0
            self._inc_opportunity_stage(stage, value_num)

        # Additional events (orders, deliveries) can update generic KPIs
        if ev_type == 'order_created' or ev_type == 'order_status_updated':
            # maintain a simple metric of order events
            try:
                resp = db.table('placeware_kpis').select('metric_value').eq('metric_key', 'order_events').limit(1).execute()
                rows = resp.data or []
                if rows:
                    new = float(rows[0].get('metric_value', 0)) + 1
                    db.table('placeware_kpis').update({'metric_value': new, 'updated_at': self._now()}).eq('metric_key', 'order_events').execute()
                else:
                    db.table('placeware_kpis').insert({'metric_key': 'order_events', 'metric_value': 1, 'updated_at': self._now()}).execute()
            except Exception as e:
                LOG.debug('Failed update order_events KPI: %s', e)

    def run(self):
        if psycopg2 is None:
            LOG.warning('psycopg2 not available; MetricsAgent exiting')
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
            LOG.exception('MetricsAgent encountered error: %s', e)
        finally:
            try:
                cur.close()
                self.conn.close()
            except Exception:
                pass


def start_in_thread(dsn: str | None = None):
    agent = MetricsAgent(dsn=dsn)
    t = threading.Thread(target=agent.run, daemon=True)
    t.start()
    return t
