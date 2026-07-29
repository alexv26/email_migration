from redis import Redis
from rq import Queue
from rq.job import Job

from webapp.config import settings
from webapp.worker_tasks import run_migration

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
