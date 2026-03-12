"""
Minimal CRM agent subscriber skeleton.

This module provides a lightweight subscriber that listens for Event Bus
notifications (Postgres NOTIFY on channel `event_bus`) and dispatches
events to registered handlers. It's a minimal, extensible starting point
for implementing the Metrics/Risk/CRM agents described in the design.

Note: This is intentionally small and dependency-light. For production,
use an event broker (Kafka, RabbitMQ) and robust retry/backoff.
"""
import os
import json
import logging
import select

try:
    import psycopg2
except Exception:
    psycopg2 = None

LOG = logging.getLogger(__name__)


class CRMEventAgent:
    def __init__(self, dsn=None, channel='event_bus'):
        self.dsn = dsn or os.getenv('DATABASE_URL')
        self.channel = channel
        self.conn = None

    def connect(self):
        if psycopg2 is None:
            raise RuntimeError('psycopg2 not installed; install dependencies to run agent')
        self.conn = psycopg2.connect(self.dsn)
        self.conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = self.conn.cursor()
        cur.execute(f"LISTEN {self.channel};")
        LOG.info('Listening on channel %s', self.channel)

    def handle_notification(self, payload):
        try:
            event = json.loads(payload)
        except Exception:
            event = {'raw': payload}
        # Simple dispatch based on event_type
        etype = event.get('event_type') or event.get('type')
        LOG.info('CRMAgent received event: %s', etype)
        # TODO: implement routing to Metrics/Risk/Inventory/Finance agents

    def run(self):
        if self.conn is None:
            self.connect()
        cur = self.conn.cursor()
        try:
            while True:
                if select.select([self.conn], [], [], 5) == ([], [], []):
                    continue
                self.conn.poll()
                while self.conn.notifies:
                    notify = self.conn.notifies.pop(0)
                    self.handle_notification(notify.payload)
        except KeyboardInterrupt:
            LOG.info('CRMEventAgent stopping')
        finally:
            cur.close()
            self.conn.close()


def main():
    logging.basicConfig(level=logging.INFO)
    agent = CRMEventAgent()
    agent.run()


if __name__ == '__main__':
    main()
