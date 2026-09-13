import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import CallJob
from app.services.retell import create_retell_call

POLL_SECONDS = 5


async def claim_and_process_once() -> bool:
    db = SessionLocal()
    job: CallJob | None = None
    try:
        job = db.scalar(
            select(CallJob)
            .where(CallJob.status == "PENDING", CallJob.scheduled_at <= datetime.now(UTC))
            .order_by(CallJob.priority.asc(), CallJob.scheduled_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return False

        job.status = "CLAIMED"
        db.commit()
        await create_retell_call(db, job)
        return True
    except Exception as exc:  # noqa: BLE001
        # ponytail: el worker debe sobrevivir fallos inesperados por trabajo.
        # Upgrade: clasificar errores reintentables cuando exista una politica de reintentos.
        db.rollback()
        if job:
            job.status = "FAILED"
            job.last_error = str(exc)
            db.commit()
        return True
    finally:
        db.close()


async def main() -> None:
    print("Worker started. Waiting for pending call jobs.")
    while True:
        processed = await claim_and_process_once()
        if not processed:
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())

