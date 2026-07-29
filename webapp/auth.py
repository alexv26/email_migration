import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from webapp.config import settings

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600

ADMIN_SESSION_COOKIE_NAME = "admin_session"
ADMIN_SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600

# Distinct salts give the two token types separate namespaces under the same
# secret - a regular user session can never be replayed as an admin session
# even though both are signed with SESSION_SECRET.
_serializer = URLSafeTimedSerializer(settings.session_secret, salt="mail-transfer-session")
_admin_serializer = URLSafeTimedSerializer(settings.session_secret, salt="mail-transfer-admin-session")


def verify_app_password(submitted: str) -> bool:
    return secrets.compare_digest(submitted or "", settings.app_password)


def verify_admin_password(submitted: str) -> bool:
    return secrets.compare_digest(submitted or "", settings.admin_password)


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


def create_admin_session_token() -> str:
    return _admin_serializer.dumps({"sid": secrets.token_urlsafe(16)})


def read_admin_session(token: str) -> dict | None:
    if not token:
        return None
    try:
        return _admin_serializer.loads(token, max_age=ADMIN_SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
