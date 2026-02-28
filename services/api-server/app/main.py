"""API server entrypoint."""

from fastapi import FastAPI

from app.api.admin_eval import router as admin_eval_router
from app.api.admin_jobs import router as admin_jobs_router
from app.api.chat import router as chat_router
from app.api.search import router as search_router
from app.api.upload import router as upload_router

app = FastAPI(title="ExpertDatebase API", version="0.1.0")
app.include_router(upload_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(admin_eval_router)
app.include_router(admin_jobs_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
