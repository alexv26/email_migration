from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from webapp.auth import SESSION_COOKIE_NAME, read_session
from webapp.routes.auth_routes import router as auth_router
from webapp.routes.migration_routes import router as migration_router

BASE_DIR = Path(__file__).resolve().parent

PUBLIC_PATHS = {"/login", "/healthz"}


class SessionAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith("/static/"):
            return await call_next(request)

        session = read_session(request.cookies.get(SESSION_COOKIE_NAME))
        if session is None:
            return RedirectResponse(url="/login", status_code=303)

        request.state.session = session
        return await call_next(request)


def create_app() -> FastAPI:
    app = FastAPI(title="Mail Transfer")
    app.add_middleware(SessionAuthMiddleware)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    app.include_router(auth_router)
    app.include_router(migration_router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


app = create_app()
