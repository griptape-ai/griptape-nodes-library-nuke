from __future__ import annotations

from execution.provider import JobResult, JobStatus


def test_job_status_has_all_five_states() -> None:
    names = {s.name for s in JobStatus}
    assert names == {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}


def test_job_result_defaults_to_empty_outputs_and_log() -> None:
    result = JobResult(handle="abc-123", status=JobStatus.SUCCEEDED, return_code=0)
    assert result.outputs == {}
    assert result.log == []
