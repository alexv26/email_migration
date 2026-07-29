import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from webapp.config import settings

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600

_serializer = URLSafeTimedSerializer(settings.session_secret, salt="mail-transfer-session")


def verify_app_password(submitted: str) -> bool:
    return secrets.compare_digest(submitted or "", settings.app_password)


def create_session_token(job_id: str | None = None) -> str:
    return _serializer.dumps({"sid": secrets.token_urlsafe(16), "job_id": job_id})


def read_session(token: str) -> dict | None:
    if not token:
        return None
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def set_session_job_id(session_data: dict, job_id: str) -> str:
    return _serializer.dumps({"sid": session_data["sid"], "job_id": job_id})
