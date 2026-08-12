from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, chains
from app.config import settings

app = FastAPI(title="Options Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(chains.router, prefix="/chains", tags=["chains"])


@app.get("/health")
def health():
    return {"status": "ok"}
