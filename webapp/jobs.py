from redis import Redis
from rq import Queue
from rq.command import send_stop_job_command
from rq.exceptions import InvalidJobOperation
from rq.job import Job
from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry

from webapp.config import settings
from webapp.worker_tasks import run_migration

CANCELABLE_STATUSES = {"queued", "deferred", "scheduled"}

_redis = Redis.from_url(settings.redis_url)
queue = Queue("default", connection=_redis)


def get_redis() -> Redis:
    return _redis


def enqueue_migration(encrypted_payload: bytes) -> Job:
    return queue.enqueue(
        run_migration,
        encrypted_payload,
        job_timeout=settings.job_timeout_seconds,
        result_ttl=settings.result_ttl_seconds,
        failure_ttl=settings.failure_ttl_seconds,
    )


def fetch_job(job_id: str):
    try:
        return Job.fetch(job_id, connection=_redis)
    except Exception:
        return None


def cancel_job(job_id: str) -> bool:
    """Stops a running job or dequeues a waiting one. Returns True if a
    cancel/stop was actually issued, False if the job wasn't found or was
    already in a terminal state (nothing to cancel)."""
    job = fetch_job(job_id)
    if job is None:
        return False

    status = job.get_status()
    if status in CANCELABLE_STATUSES:
        job.cancel()
        return True
    if status == "started":
        try:
            send_stop_job_command(_redis, job_id)
            return True
        except InvalidJobOperation:
            return False
    return False


def list_active_and_recent_jobs():
    """All jobs currently queued/running, plus any finished/failed jobs that
    haven't been cleaned up yet (either their TTL hasn't expired, or nobody
    ever polled /api/status/<id> to trigger the immediate delete)."""
    job_ids = set(queue.job_ids)
    job_ids |= set(StartedJobRegistry(queue=queue).get_job_ids())
    job_ids |= set(FinishedJobRegistry(queue=queue).get_job_ids())
    job_ids |= set(FailedJobRegistry(queue=queue).get_job_ids())

    jobs = [fetch_job(job_id) for job_id in job_ids]
    return [job for job in jobs if job is not None]
