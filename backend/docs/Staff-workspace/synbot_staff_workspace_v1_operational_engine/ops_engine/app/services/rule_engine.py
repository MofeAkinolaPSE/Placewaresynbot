from datetime import timedelta
from typing import Any
from app.models.event import OperationalEvent

class OperationalRuleEngine:
    """Pure matching/rendering logic. Database access belongs in repositories."""

    @staticmethod
    def matches(rule: Any, event: OperationalEvent) -> bool:
        if not getattr(rule, 'enabled', False):
            return False
        if rule.event_type != event.event_type:
            return False
        if rule.company_id is not None and rule.company_id != event.company_id:
            return False
        if rule.entity_type and rule.entity_type != event.entity_type:
            return False
        conditions = rule.conditions or {}
        for key, expected in conditions.items():
            if event.payload.get(key) != expected:
                return False
        return True

    @staticmethod
    def render(template: str | None, event: OperationalEvent) -> str | None:
        if template is None:
            return None
        values = {
            'event_type': event.event_type,
            'entity_type': event.entity_type,
            'entity_id': event.entity_id,
            **event.payload,
        }
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            # Do not fail an operational event because an optional template token is absent.
            return template

    @staticmethod
    def due_at(rule: Any, event: OperationalEvent):
        if rule.due_minutes is None:
            return None
        return event.occurred_at + timedelta(minutes=rule.due_minutes)
