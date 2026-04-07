from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.backend.api.routes.auth import router as auth_router
from app.backend.api.routes.feed import router as feed_router
from app.backend.api.routes.health import router as health_router
from app.backend.api.routes.ingestion import router as ingestion_router
from app.backend.api.routes.pipeline import router as pipeline_router
from app.backend.core.config import settings

app = FastAPI(title="PDADS MVP")

cors_origins = settings.cors_allow_origins
cors_origin_regex = settings.cors_allow_origin_regex

# credentials=True is incompatible with a bare wildcard origin ("*").
# When specific origins or a regex are provided, credentials can be enabled
# so cookies / Authorization headers are forwarded correctly.
allow_credentials = "*" not in cors_origins

app.add_middleware(
	CORSMiddleware,
	allow_origins=cors_origins,
	allow_origin_regex=cors_origin_regex,
	allow_credentials=allow_credentials,
	allow_methods=["*"],
	allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(ingestion_router)
app.include_router(feed_router)
app.include_router(pipeline_router)

_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
	app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")