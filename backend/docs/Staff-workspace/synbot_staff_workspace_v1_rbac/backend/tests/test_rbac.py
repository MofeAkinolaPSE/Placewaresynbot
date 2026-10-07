from uuid import uuid4
from app.rbac.access import AccessContext

def test_access_context_permission_check():
    access = AccessContext(uuid4(), uuid4(), uuid4(), None, None, None, frozenset({'task:view','task:create'}))
    assert access.can('task','view')
    assert access.can('task','create')
    assert not access.can('task','delete')
