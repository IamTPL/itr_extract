from enum import Enum


class JobStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    SUCCESS    = "success"
    FAILED     = "failed"


TERMINAL_STATUSES = frozenset({JobStatus.SUCCESS, JobStatus.FAILED})
ACTIVE_STATUSES   = frozenset({JobStatus.PENDING, JobStatus.PROCESSING})
