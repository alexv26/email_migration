import os


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class Settings:
    def __init__(self):
        self.app_password = _required("APP_PASSWORD")
        self.admin_password = _required("ADMIN_PASSWORD")
        self.session_secret = _required("SESSION_SECRET")
        self.fernet_key = _required("FERNET_KEY")
        self.redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        self.max_threads = int(os.environ.get("MAX_THREADS", "2"))
        # Messages fetched per IMAP command. Peak memory during a migration
        # scales roughly as threads * bulk_size * avg_message_size - keep
        # this low on memory-constrained hosts (see mail_transfer/core.py).
        self.bulk_size = int(os.environ.get("FETCH_BULK_SIZE", "20"))
        self.result_ttl_seconds = int(os.environ.get("RESULT_TTL_SECONDS", "600"))
        self.failure_ttl_seconds = int(os.environ.get("FAILURE_TTL_SECONDS", "600"))
        self.job_timeout_seconds = int(os.environ.get("JOB_TIMEOUT_SECONDS", "21600"))
        self.submit_rate_limit_per_hour = int(os.environ.get("SUBMIT_RATE_LIMIT_PER_HOUR", "3"))
        self.login_rate_limit_per_hour = int(os.environ.get("LOGIN_RATE_LIMIT_PER_HOUR", "20"))
        # Cookies must be `secure` (HTTPS-only) in production (Render). Only
        # disable for local http://localhost development.
        self.cookie_secure = os.environ.get("COOKIE_SECURE", "true").lower() != "false"


settings = Settings()
