from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from webapp.auth import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, create_session_token, verify_app_password
from webapp.config import settings
from webapp.jobs import get_redis
from webapp.ratelimit import check_rate_limit
from webapp.templating import templates

router = APIRouter()


@router.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    client_ip = request.client.host if request.client else "unknown"
    allowed = check_rate_limit(get_redis(), f"login:{client_ip}", settings.login_rate_limit_per_hour)
    if not allowed:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Too many attempts. Try again later."},
            status_code=429,
        )

    if not verify_app_password(password):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Incorrect password."},
            status_code=401,
        )

    token = create_session_token()
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME, token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True, secure=settings.cookie_secure, samesite="lax",
    )
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
