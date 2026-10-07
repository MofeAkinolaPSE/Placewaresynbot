from app.models.event import OperationalEvent
from app.services.rule_engine import OperationalRuleEngine

class OperationalTaskService:
    def __init__(self, rule_repo, task_repo, assignee_resolver, activity_service=None):
        self.rule_repo = rule_repo
        self.task_repo = task_repo
        self.assignee_resolver = assignee_resolver
        self.activity_service = activity_service

    async def handle_event(self, event: OperationalEvent):
        rules = await self.rule_repo.find_candidates(event.event_type, event.company_id)
        created, skipped = [], []
        matched = 0
        for rule in rules:
            if not OperationalRuleEngine.matches(rule, event):
                continue
            matched += 1
            fingerprint = f'{event.event_id}:{rule.id}'
            existing = await self.task_repo.find_by_source_event(fingerprint)
            if existing:
                skipped.append(str(existing.id))
                continue
            staff_id = await self.assignee_resolver.resolve(rule, event)
            title = OperationalRuleEngine.render(rule.title_template, event)
            description = OperationalRuleEngine.render(rule.description_template, event)
            task = await self.task_repo.create_operational_task(
                company_id=event.company_id,
                assigned_to=staff_id,
                title=title,
                description=description,
                priority=rule.priority,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                due_at=OperationalRuleEngine.due_at(rule, event),
                source_event_id=fingerprint,
                source_rule_id=rule.id,
            )
            created.append(str(task.id))
            if self.activity_service:
                await self.activity_service.record(task.id, 'created_from_operational_event', {
                    'event_id': event.event_id,
                    'event_type': event.event_type,
                    'rule_id': rule.id,
                })
        return {'event_id': event.event_id, 'matched_rules': matched, 'created_task_ids': created, 'skipped_task_ids': skipped}
