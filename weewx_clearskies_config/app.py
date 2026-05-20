from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from weewx_clearskies_config.auth import (
    COOKIE_NAME,
    BootstrapManager,
    RateLimiter,
    SessionManager,
    hash_password,
    read_secrets,
    verify_password,
    write_secrets,
)
from weewx_clearskies_config.config.routes import create_config_router
from weewx_clearskies_config.wizard.routes import create_wizard_router


@dataclass
class AppConfig:
    bind_host: str
    bind_port: int
    tls_enabled: bool
    tls_cert_path: Path | None
    tls_key_path: Path | None
    config_dir: Path
    bootstrap_manager: BootstrapManager | None = field(default=None)


def _templates_dir() -> Path:
    # Locate the templates directory relative to this package file
    return Path(__file__).parent / "templates"


def _static_dir() -> Path:
    return Path(__file__).parent / "static"


class _RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, rate_limiter: RateLimiter) -> None:
        super().__init__(app)
        self._limiter = rate_limiter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method == "POST" and request.url.path == "/login":
            client_ip = request.client.host if request.client else "unknown"
            if self._limiter.is_throttled(client_ip):
                return HTMLResponse(
                    content="Too many failed login attempts. Please wait 60 seconds.",
                    status_code=429,
                )
        return await call_next(request)


def create_app(config: AppConfig) -> FastAPI:
    app = FastAPI(title="Clear Skies Config", docs_url=None, redoc_url=None)

    templates = Jinja2Templates(directory=str(_templates_dir()))
    rate_limiter = RateLimiter()
    session_manager = SessionManager(tls_enabled=config.tls_enabled)
    bootstrap_manager = config.bootstrap_manager or BootstrapManager()

    app.add_middleware(_RateLimitMiddleware, rate_limiter=rate_limiter)
    app.mount("/static", StaticFiles(directory=str(_static_dir())), name="static")

    # Mount the wizard router.  create_wizard_router() injects shared objects
    # (templates, session_manager, config_dir) that the router endpoints need.
    wizard_router = create_wizard_router(
        templates=templates,
        session_manager=session_manager,
        config_dir=config.config_dir,
    )
    app.include_router(wizard_router)

    # Mount the config router.  create_config_router() injects shared objects
    # (templates, session_manager, config_dir) that the router endpoints need.
    config_router = create_config_router(
        templates=templates,
        session_manager=session_manager,
        config_dir=config.config_dir,
    )
    app.include_router(config_router)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/")
    async def root() -> RedirectResponse:
        secrets = read_secrets()
        if "WEEWX_CLEARSKIES_ADMIN_USERNAME" not in secrets:
            return RedirectResponse(url="/bootstrap", status_code=302)
        # If no api.conf exists yet, redirect to the setup wizard.
        if not (config.config_dir / "api.conf").exists():
            return RedirectResponse(url="/wizard", status_code=302)
        return RedirectResponse(url="/login", status_code=302)

    @app.get("/login", response_class=HTMLResponse)
    async def login_get(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": None},
        )

    @app.post("/login")
    async def login_post(request: Request) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))

        stored = read_secrets()
        stored_username = stored.get("WEEWX_CLEARSKIES_ADMIN_USERNAME", "")
        stored_hash = stored.get("WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH", "")

        if (
            stored_hash
            and secrets.compare_digest(username, stored_username)
            and verify_password(password, stored_hash)
        ):
            rate_limiter.record_success(client_ip)
            session_id = session_manager.create(username)
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie(
                **{k: v for k, v in session_manager.cookie_kwargs.items()},
                value=session_id,
            )
            return response

        rate_limiter.record_failure(client_ip)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password."},
            status_code=401,
        )

    @app.post("/logout")
    async def logout(request: Request) -> RedirectResponse:
        session_id = request.cookies.get(COOKIE_NAME, "")
        session_manager.delete(session_id)
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @app.get("/bootstrap", response_class=HTMLResponse)
    async def bootstrap_get(request: Request, token: str = "") -> HTMLResponse:
        # GET only shows the form; token is passed through to the POST action.
        # Validation (and single-use consumption) happens on POST only.
        token_present = bool(token)
        return templates.TemplateResponse(
            request=request,
            name="bootstrap.html",
            context={"token": token, "token_valid": token_present, "error": None},
        )

    @app.post("/bootstrap")
    async def bootstrap_post(request: Request, token: str = "") -> Response:
        # Validate and consume the token on POST only.
        if not token or not bootstrap_manager.validate(token):
            return templates.TemplateResponse(
                request=request,
                name="bootstrap.html",
                context={
                    "token": token,
                    "token_valid": False,
                    "error": "Invalid or expired bootstrap token.",
                },
                status_code=400,
            )

        form = await request.form()
        new_username = str(form.get("username", "")).strip()
        new_password = str(form.get("password", ""))
        confirm_password = str(form.get("confirm_password", ""))

        if not new_username or not new_password:
            return templates.TemplateResponse(
                request=request,
                name="bootstrap.html",
                context={
                    "token": token,
                    "token_valid": True,
                    "error": "Username and password are required.",
                },
                status_code=400,
            )

        if new_password != confirm_password:
            return templates.TemplateResponse(
                request=request,
                name="bootstrap.html",
                context={
                    "token": token,
                    "token_valid": True,
                    "error": "Passwords do not match.",
                },
                status_code=400,
            )

        if len(new_password) < 12:
            return templates.TemplateResponse(
                request=request,
                name="bootstrap.html",
                context={
                    "token": token,
                    "token_valid": True,
                    "error": "Password must be at least 12 characters.",
                },
                status_code=400,
            )

        existing = read_secrets()
        existing["WEEWX_CLEARSKIES_ADMIN_USERNAME"] = new_username
        existing["WEEWX_CLEARSKIES_ADMIN_PASSWORD_HASH"] = hash_password(new_password)
        write_secrets(existing)

        return RedirectResponse(url="/login", status_code=303)

    return app
