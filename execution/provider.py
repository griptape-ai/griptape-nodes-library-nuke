from __future__ import annotations

import enum
from dataclasses import dataclass, field


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobResult:
    handle: str
    status: JobStatus
    return_code: int
    outputs: dict[str, str] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
