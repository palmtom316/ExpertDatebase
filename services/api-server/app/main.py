"""API server entrypoint."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_docs import router as admin_docs_router
from app.api.admin_eval import router as admin_eval_router
from app.api.admin_jobs import router as admin_jobs_router
from app.api.chat import router as chat_router
from app.api.search import router as search_router
from app.api.upload import router as upload_router

app = FastAPI(title="ExpertDatebase API", version="0.1.0")

cors_origins_raw = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
cors_origins = [item.strip() for item in cors_origins_raw.split(",") if item.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(upload_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(admin_eval_router)
app.include_router(admin_jobs_router)
app.include_router(admin_docs_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
