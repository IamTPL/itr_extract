from config.enums import JobStatus, TERMINAL_STATUSES, ACTIVE_STATUSES


def test_job_status_values():
    assert JobStatus.PENDING.value == "pending"
    assert JobStatus.PROCESSING.value == "processing"
    assert JobStatus.SUCCESS.value == "success"
    assert JobStatus.FAILED.value == "failed"


def test_status_sets_partition_correctly():
    all_statuses = {s for s in JobStatus}
    assert TERMINAL_STATUSES | ACTIVE_STATUSES == all_statuses
    assert TERMINAL_STATUSES & ACTIVE_STATUSES == set()
