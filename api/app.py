from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from config.settings import get_settings, validate_production_config
from api import health, jobs, me
from api.limiter import limiter


# CSP cho REST API only — không serve HTML, nên restrictive nhất có thể
_API_CSP = "default-src 'none'; frame-ancestors 'none'"

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": _API_CSP,
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


def create_app() -> FastAPI:
    # Fail-fast: nếu ENVIRONMENT=production mà thiếu MSAL_TENANT_ID etc → raise
    # ngay khi tạo app, không cho server start với cấu hình lỏng.
    validate_production_config(get_settings())

    app = FastAPI(title="ITR Extract API", version="2.0.0")
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().allowed_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Rate limit theo IP (defense-in-depth, không thay thế per-user quota DB).
    # SlowAPIMiddleware apply default_limits cho TẤT CẢ routes.
    # Endpoints tốn kém (POST /api/jobs, /reprocess) có decorator riêng siết chặt hơn.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(jobs.router)
    return app
