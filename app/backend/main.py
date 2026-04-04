from fastapi import FastAPI
from app.backend.api.routes.pipeline import router as pipeline_router

app = FastAPI(title="PDADS MVP")
app.include_router(pipeline_router)