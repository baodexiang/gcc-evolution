from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


VALID_TRANSITIONS = {
    "queued": {"running", "failed", "timeout"},
    "running": {"partial_success", "success", "failed", "timeout"},
    "partial_success": set(),
    "success": set(),
    "failed": set(),
    "timeout": set(),
}


@dataclass
class BatchJob:
    job_id: str
    tickers: List[str]
    status: str = "queued"
    progress_pct: float = 0.0
    finished_count: int = 0
    failed_count: int = 0
    retry_count: int = 0
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


@dataclass
class BatchJobStore:
    jobs: Dict[str, BatchJob] = field(default_factory=dict)

    def create(self, job_id: str, tickers: List[str]) -> BatchJob:
        job = BatchJob(job_id=job_id, tickers=tickers)
        self.jobs[job_id] = job
        return job

    def transition(self, job_id: str, next_status: str) -> BatchJob:
        job = self.jobs[job_id]
        allowed = VALID_TRANSITIONS.get(job.status, set())
        if next_status not in allowed:
            raise ValueError(f"invalid transition: {job.status} -> {next_status}")
        if next_status == "running" and not job.started_at:
            job.started_at = datetime.utcnow().isoformat()
        if next_status in {"partial_success", "success", "failed", "timeout"}:
            job.ended_at = datetime.utcnow().isoformat()
        job.status = next_status
        return job

    def snapshot(self, job_id: str) -> Dict[str, object]:
        j = self.jobs[job_id]
        return {
            "job_id": j.job_id,
            "status": j.status,
            "progress_pct": j.progress_pct,
            "finished_count": j.finished_count,
            "failed_count": j.failed_count,
            "retry_count": j.retry_count,
            "started_at": j.started_at,
            "ended_at": j.ended_at,
        }
