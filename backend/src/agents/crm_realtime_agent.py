"""CRM realtime agent: listens to Postgres NOTIFY 'event_bus', enriches KG and refreshes customer_360."""
import threading
import time
import logging
import json
from typing import Optional

import psycopg2
import psycopg2.extensions

import src.db as db
from src.services import kg_graph

logger = logging.getLogger(__name__)


class CRMRealtimeAgent:
    def __init__(self, dsn: Optional[str] = None, poll_interval: int = 5):
        # DSN optional: fallback to env DATABASE_URL
        self.dsn = dsn
        self.poll_interval = poll_interval
        self._running = False

    def _ensure_node(self, node_type: str, external_id: str, attrs: dict):
        return kg_graph.ensure_node(
            node_type=node_type,
            ref_table=node_type,
            ref_value=str(external_id),
            properties=attrs or {},
        )

    def _ensure_edge(self, from_id: str, to_id: str, edge_type: str, attrs: dict = None):
        return kg_graph.ensure_edge(
            from_node=int(from_id) if str(from_id).isdigit() else None,
            to_node=int(to_id) if str(to_id).isdigit() else None,
            edge_type=edge_type,
            properties=attrs or {},
        )

    def _process_event(self, event: dict):
        try:
            # Example: create event node and link to customer/opportunity
            event_id = str(event.get('event_id') or '')
            event_node = self._ensure_node('event', event_id, {'event_type': event.get('event_type'), 'created_at': event.get('created_at')})

            cust = event.get('linked_customer_id')
            if cust:
                cust_id = str(cust)
                cust_node = self._ensure_node('customer', cust_id, {})
                kg_graph.ensure_edge(from_node=cust_node, to_node=event_node, edge_type='LinkedTo', properties={})
                # refresh customer_360 via DB function if available
                try:
                    # use raw SQL to call refresh function
                    conn = psycopg2.connect(db.get_psycopg_dsn())
                    conn.autocommit = True
                    with conn.cursor() as cur:
                        cur.execute("SELECT refresh_customer_360(%s);", (cust,))
                    conn.close()
                except Exception:
                    logger.exception('Failed calling refresh_customer_360 for %s', cust)

            opp = event.get('linked_opportunity_id')
            if opp:
                opp_id = str(opp)
                opp_node = self._ensure_node('opportunity', opp_id, {})
                kg_graph.ensure_edge(from_node=opp_node, to_node=event_node, edge_type='LinkedTo', properties={})
                if cust:
                    cust_node = self._ensure_node('customer', str(cust), {})
                    kg_graph.ensure_edge(from_node=opp_node, to_node=cust_node, edge_type='LinkedTo', properties={})

        except Exception:
            logger.exception('Failed processing event %s', event)

    def _listen_loop(self):
        try:
            dsn = self.dsn or db.get_psycopg_dsn()
            conn = psycopg2.connect(dsn)
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            cur = conn.cursor()
            cur.execute("LISTEN event_bus;")
            logger.info('CRMRealtimeAgent listening on event_bus')
            while self._running:
                if select_available(conn, timeout=self.poll_interval):
                    conn.poll()
                    while conn.notifies:
                        notify = conn.notifies.pop(0)
                        try:
                            payload = json.loads(notify.payload)
                        except Exception:
                            payload = {"event_id": notify.payload}
                        event_id = payload.get('event_id')
                        if not event_id:
                            continue
                        # fetch full event via supabase
                        try:
                            res = db.table('event_ledger').select('*').eq('event_id', event_id).limit(1).execute()
                            rows = res.data or []
                            if rows:
                                self._process_event(rows[0])
                        except Exception:
                            logger.exception('Failed fetching event %s', event_id)
                else:
                    time.sleep(self.poll_interval)
        except Exception:
            logger.exception('CRMRealtimeAgent listen loop failed')

    def run(self):
        self._running = True
        try:
            self._listen_loop()
        finally:
            self._running = False

    def stop(self):
        self._running = False


def select_available(conn, timeout: int = 5):
    import select as _select
    fileno = conn.fileno()
    r, w, x = _select.select([fileno], [], [], timeout)
    return bool(r)


def start_in_thread(dsn: Optional[str] = None, poll_interval: int = 5):
    agent = CRMRealtimeAgent(dsn=dsn, poll_interval=poll_interval)
    t = threading.Thread(target=agent.run, daemon=True)
    t.start()
    return agent
