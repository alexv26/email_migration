from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from webapp.auth import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, set_session_job_id
from webapp.config import settings
from webapp.jobs import enqueue_migration, fetch_job, get_redis
from webapp.ratelimit import check_rate_limit
from webapp.security import UnsafeHostError, encrypt_payload, validate_public_host
from webapp.templating import templates

router = APIRouter()

ACTIVE_JOB_STATUSES = {"queued", "started", "deferred", "scheduled"}
TERMINAL_JOB_STATUSES = {"finished", "failed"}


@router.get("/")
async def submit_form(request: Request):
    return templates.TemplateResponse(request, "submit.html", {"max_threads": settings.max_threads})


@router.post("/migrate")
async def submit_migration(
    request: Request,
    source_imap_host: str = Form(...),
    source_email: str = Form(...),
    source_password: str = Form(...),
    dest_imap_host: str = Form(...),
    dest_email: str = Form(...),
    dest_password: str = Form(...),
    threads: int = Form(...),
    copy_inbox: str = Form(...),
):
    session = request.state.session

    existing_job_id = session.get("job_id")
    if existing_job_id:
        existing = fetch_job(existing_job_id)
        if existing is not None and existing.get_status() in ACTIVE_JOB_STATUSES:
            return RedirectResponse(url=f"/status/{existing_job_id}", status_code=303)

    if not check_rate_limit(get_redis(), f"submit:{session['sid']}", settings.submit_rate_limit_per_hour):
        raise HTTPException(status_code=429, detail="Too many migrations submitted. Try again later.")

    if not (1 <= threads <= settings.max_threads):
        raise HTTPException(status_code=422, detail=f"threads must be between 1 and {settings.max_threads}")

    if copy_inbox not in ("y", "n"):
        raise HTTPException(status_code=422, detail="copy_inbox must be 'y' or 'n'")

    try:
        validate_public_host(source_imap_host)
        validate_public_host(dest_imap_host)
    except UnsafeHostError:
        raise HTTPException(status_code=400, detail="One of the IMAP hosts isn't reachable.")

    payload = {
        "source": {"imap_host": source_imap_host, "email": source_email, "password": source_password},
        "dest": {"imap_host": dest_imap_host, "email": dest_email, "password": dest_password},
        "threads": threads,
        "copy_inbox": copy_inbox,
    }
    job = enqueue_migration(encrypt_payload(payload))

    new_token = set_session_job_id(session, job.id)
    response = RedirectResponse(url=f"/status/{job.id}", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME, new_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True, secure=settings.cookie_secure, samesite="lax",
    )
    return response


@router.get("/status/{job_id}")
async def status_page(request: Request, job_id: str):
    session = request.state.session
    if job_id != session.get("job_id"):
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "status.html", {"job_id": job_id})


@router.get("/api/status/{job_id}")
async def status_api(request: Request, job_id: str):
    session = request.state.session
    if job_id != session.get("job_id"):
        raise HTTPException(status_code=404)

    job = fetch_job(job_id)
    if job is None:
        return JSONResponse({"job_status": "gone"}, status_code=404)

    job_status = job.get_status()
    body = {"job_status": job_status, "meta": job.meta}

    if job_status in TERMINAL_JOB_STATUSES:
        if job_status == "failed" and not body["meta"].get("error"):
            body["meta"] = dict(body["meta"])
            body["meta"]["error"] = "Migration failed."
        # Clean up now that the client has the final state - nothing about
        # this job (including the encrypted credential payload) should
        # linger in Redis longer than necessary.
        job.delete()

    return JSONResponse(body)
