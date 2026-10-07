class AssigneeResolver:
    """Resolve task ownership from an operational event and rule.

    Repository implementations are injected by the host Synbot application.
    """
    def __init__(self, staff_repo, team_repo=None, role_repo=None):
        self.staff_repo = staff_repo
        self.team_repo = team_repo
        self.role_repo = role_repo

    async def resolve(self, rule, event):
        mode = rule.assign_mode
        if mode == 'event_actor':
            return event.actor_staff_id
        if mode == 'staff':
            return int(rule.assign_value) if rule.assign_value else None
        if mode == 'team':
            return await self.staff_repo.find_available_by_team(event.company_id, event.team_id, rule.assign_value)
        if mode == 'department':
            return await self.staff_repo.find_available_by_department(event.company_id, event.department_id, rule.assign_value)
        if mode == 'facility':
            return await self.staff_repo.find_available_by_facility(event.company_id, event.facility_id, rule.assign_value)
        if mode == 'role' and self.role_repo:
            return await self.role_repo.find_available_staff(event.company_id, rule.assign_value, event.department_id, event.facility_id)
        return None
