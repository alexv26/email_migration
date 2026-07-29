import threading
import time
from datetime import datetime, timezone

from mail_transfer.progress import ProgressReporter
from webapp.security import scrub_secrets


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RQProgressReporter(ProgressReporter):
    """Writes structured, PII-minimal progress into an RQ job's `meta` dict.

    Called concurrently from multiple worker threads (one per folder, via
    the ThreadPoolExecutor in mail_transfer.core), so all meta mutation is
    lock-guarded. Per-message writes are throttled to avoid hammering Redis;
    folder/job start/finish/error events always flush immediately.
    """

    def __init__(self, job, secret_values, min_interval: float = 0.5):
        self._job = job
        self._secret_values = list(secret_values)
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_write = {}

    def _flush(self):
        self._job.meta["updated_at"] = _now_iso()
        self._job.save_meta()

    def start_job(self, total_folders, folder_names):
        with self._lock:
            self._job.meta.update({
                "status": "running",
                "total_folders": total_folders,
                "folders_done": 0,
                "folders": {
                    name: {"total": 0, "done": 0, "state": "pending"}
                    for name in folder_names
                },
                "error": None,
                "started_at": _now_iso(),
            })
            self._flush()

    def start_folder(self, folder_name, total_messages):
        with self._lock:
            self._job.meta["folders"][folder_name] = {
                "total": total_messages,
                "done": 0,
                "state": "running",
            }
            self._flush()

    def advance_message(self, folder_name, done, total):
        with self._lock:
            entry = self._job.meta["folders"].get(folder_name)
            if entry is None:
                return
            entry["done"] = done
            entry["total"] = total

            now = time.monotonic()
            last = self._last_write.get(folder_name, 0)
            if now - last >= self._min_interval:
                self._last_write[folder_name] = now
                self._flush()

    def finish_folder(self, folder_name):
        with self._lock:
            entry = self._job.meta["folders"].get(folder_name)
            if entry is not None:
                entry["state"] = "done"
            self._job.meta["folders_done"] = self._job.meta.get("folders_done", 0) + 1
            self._flush()

    def finish_job(self):
        with self._lock:
            self._job.meta["status"] = "done"
            self._flush()

    def error(self, folder_name, message):
        scrubbed = scrub_secrets(message, self._secret_values)
        with self._lock:
            if folder_name is not None:
                entry = self._job.meta["folders"].get(folder_name)
                if entry is not None:
                    entry["state"] = "error"
            self._job.meta["status"] = "error"
            self._job.meta["error"] = scrubbed
            self._flush()
