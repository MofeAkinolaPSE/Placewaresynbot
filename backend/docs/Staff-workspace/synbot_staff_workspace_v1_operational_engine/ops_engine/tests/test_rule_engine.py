from types import SimpleNamespace
from datetime import datetime, timezone
from app.models.event import OperationalEvent
from app.services.rule_engine import OperationalRuleEngine

def test_matches_and_renders():
    rule = SimpleNamespace(enabled=True, event_type='shipment.received', entity_type='shipment', company_id=4, conditions={'status':'received'}, title_template='Receive shipment {entity_id}', due_minutes=30)
    event = OperationalEvent('evt-1','shipment.received','shipment','S-100',4,payload={'status':'received'})
    assert OperationalRuleEngine.matches(rule, event)
    assert OperationalRuleEngine.render(rule.title_template, event) == 'Receive shipment S-100'
    assert OperationalRuleEngine.due_at(rule, event).tzinfo == timezone.utc

def test_non_matching_condition():
    rule = SimpleNamespace(enabled=True, event_type='shipment.received', entity_type='shipment', company_id=4, conditions={'status':'received'})
    event = OperationalEvent('evt-1','shipment.received','shipment','S-100',4,payload={'status':'pending'})
    assert not OperationalRuleEngine.matches(rule, event)
