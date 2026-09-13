from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import calls, customers, health, retell
from app.core.config import settings

app = FastAPI(title="Banca Inteligente Retell", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(customers.router, prefix="/api/v1")
app.include_router(calls.router, prefix="/api/v1")
app.include_router(retell.router, prefix="/api/v1/retell")

