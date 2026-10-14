import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import audit, auth, bills, dashboard, facilities, factors, reports, review, users
from app.config import get_settings
from app.pipeline.queue import get_queue, requeue_unfinished

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().requeue_on_startup:
        requeue_unfinished()
    yield
    get_queue().shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="GreenTrace API", version="0.2.0", lifespan=lifespan)
    # Any origin may call the API. That is safe here because login is a Bearer token sent in the
    # Authorization header (no cookies), so a foreign site cannot ride on the user's session, and
    # allow_credentials stays False. This means no per-deployment origin list is needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Page-Count", "X-Highlight"],
        max_age=86400,
    )

    api = APIRouter(prefix="/api")
    for module in (auth, users, facilities, factors, bills, review, dashboard, reports, audit):
        api.include_router(module.router)

    @api.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    app.include_router(api)
    return app


app = create_app()
