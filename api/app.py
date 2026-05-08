from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from config.constants import USER_RATE_LIMIT
from config.settings import get_settings
from api import health, jobs, me


def create_app() -> FastAPI:
    app = FastAPI(title="ITR Extract API", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().allowed_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    limiter = Limiter(key_func=get_remote_address, default_limits=[USER_RATE_LIMIT])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(jobs.router)
    return app
