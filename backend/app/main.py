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
    settings = get_settings()
    app = FastAPI(title="GreenTrace API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Page-Count", "X-Highlight"],
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
