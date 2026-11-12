"""Declared record source, never a name/mode heuristic or deletion permission."""
BUSINESS_SOURCES=frozenset({'manual','ai','template','training','rollback','capture','deploy'})
TEST_SOURCES=frozenset({'test','test_fixture','acceptance_test','ui_test'})


def declared_origin(source):
    if source in TEST_SOURCES:return 'test'
    if source in BUSINESS_SOURCES:return 'normal'
    return 'unknown'


def background_origin(task_type):
    # This legacy table has no source column. Only explicit test types convey
    # that declaration; a functional task type/name does not establish origin.
    return 'test' if task_type in TEST_SOURCES else 'unknown'
