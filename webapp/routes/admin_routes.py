from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from webapp.auth import (
    ADMIN_SESSION_COOKIE_NAME,
    ADMIN_SESSION_MAX_AGE_SECONDS,
    create_admin_session_token,
    read_admin_session,
    verify_admin_password,
)
from webapp.config import settings
from webapp.jobs import get_redis, list_active_and_recent_jobs
from webapp.ratelimit import check_rate_limit
from webapp.templating import templates

router = APIRouter()


def _require_admin(request: Request) -> dict | None:
    return read_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE_NAME))


@router.get("/admin/login")
async def admin_login_form(request: Request):
    return templates.TemplateResponse(request, "admin_login.html", {"error": None})


@router.post("/admin/login")
async def admin_login_submit(request: Request, password: str = Form(...)):
    client_ip = request.client.host if request.client else "unknown"
    allowed = check_rate_limit(get_redis(), f"admin-login:{client_ip}", settings.login_rate_limit_per_hour)
    if not allowed:
        return templates.TemplateResponse(
            request, "admin_login.html",
            {"error": "Too many attempts. Try again later."},
            status_code=429,
        )

    if not verify_admin_password(password):
        return templates.TemplateResponse(
            request, "admin_login.html",
            {"error": "Incorrect password."},
            status_code=401,
        )

    token = create_admin_session_token()
    response = RedirectResponse(url="/admin/jobs", status_code=303)
    response.set_cookie(
        ADMIN_SESSION_COOKIE_NAME, token,
        max_age=ADMIN_SESSION_MAX_AGE_SECONDS,
        httponly=True, secure=settings.cookie_secure, samesite="lax",
    )
    return response


@router.post("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(ADMIN_SESSION_COOKIE_NAME)
    return response


@router.get("/admin/jobs")
async def admin_jobs_page(request: Request):
    if _require_admin(request) is None:
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse(request, "admin_jobs.html", {})


@router.get("/admin/api/jobs")
async def admin_jobs_api(request: Request):
    if _require_admin(request) is None:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    jobs = list_active_and_recent_jobs()
    body = [
        {
            "job_id": job.id,
            "job_status": job.get_status(),
            "meta": job.meta,
            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
        }
        for job in jobs
    ]
    # Newest first.
    body.sort(key=lambda j: j["enqueued_at"] or "", reverse=True)
    return JSONResponse(body)
