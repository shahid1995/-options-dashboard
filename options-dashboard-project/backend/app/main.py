from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db import init_db
from app.routers import annotations, auth, chains, paper, resolve, templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Options Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Session-Id"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(chains.router, prefix="/chains", tags=["chains"])
app.include_router(paper.router, prefix="/paper", tags=["paper"])
app.include_router(templates.router, prefix="/paper", tags=["templates"])
app.include_router(resolve.router, prefix="/paper", tags=["resolve"])
app.include_router(annotations.router, tags=["annotations"])


@app.get("/health")
def health():
    return {"status": "ok"}
