from app.services.tasks import ALLOWED

def test_task_lifecycle_rules():
    assert 'accepted' in ALLOWED['inbox']
    assert 'in_progress' in ALLOWED['accepted']
    assert 'completed' in ALLOWED['in_progress']
    assert 'in_progress' in ALLOWED['waiting']
    assert 'closed' in ALLOWED['verified']
