import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import calls, customers, health, retell
from app.core.config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = None
    if settings.run_worker_in_web:
        from app.worker.runner import main as run_worker

        # ponytail: el MVP comparte un proceso gratuito para API + worker.
        # Techo: Render duerme el servicio; separar en worker pagado para producción.
        worker = asyncio.create_task(run_worker())
    yield
    if worker:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title="Banca Inteligente Retell", version="0.1.0", lifespan=lifespan)

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
