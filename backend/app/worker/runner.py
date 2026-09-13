import asyncio
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import CallJob, Campaign, Customer
from app.services.retell import create_retell_call

POLL_SECONDS = 5
# Regla dura del guion para El Salvador: lunes a viernes, 08:00-18:00.
# La campaña puede restringirla vía rules_json["allowed_window"].
# ponytail: la ventana del contacto (preferred_call_window) no se intersecta aquí;
# upgrade: aplicar la más restrictiva de ambas.
DEFAULT_CALL_WINDOW = "08:00-18:00"


def parse_call_window(value: str | None) -> tuple[dt_time, dt_time]:
    try:
        start_s, separator, end_s = (value or DEFAULT_CALL_WINDOW).partition("-")
        start = dt_time.fromisoformat(start_s.strip())
        end = dt_time.fromisoformat(end_s.strip())
        if separator and start < end:
            return start, end
    except ValueError:
        pass
    return dt_time(8, 0), dt_time(18, 0)


def inside_call_window(now_local: datetime, start: dt_time, end: dt_time) -> bool:
    return now_local.weekday() < 5 and start <= now_local.time() < end


def next_call_window_start(now_local: datetime, start: dt_time) -> datetime:
    candidate = now_local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    if candidate <= now_local:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


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

        customer = db.get(Customer, job.customer_id)
        campaign = db.get(Campaign, job.campaign_id)
        now = datetime.now(UTC)

        if campaign and campaign.starts_at and now < campaign.starts_at:
            job.status = "PENDING"
            job.scheduled_at = campaign.starts_at
            db.commit()
            return True

        if campaign and campaign.ends_at and now > campaign.ends_at:
            job.status = "BLOCKED"
            job.last_error = "Campaña finalizada"
            db.commit()
            return True

        allowed_window = (campaign.rules_json or {}).get("allowed_window") if campaign else None
        start, end = parse_call_window(allowed_window)
        now_local = now.astimezone(ZoneInfo(customer.timezone if customer else "UTC"))
        if not inside_call_window(now_local, start, end):
            # Fuera de ventana hábil: reponer el trabajo para el próximo horario,
            # sin crear registro de llamada.
            job.status = "PENDING"
            job.scheduled_at = next_call_window_start(now_local, start).astimezone(UTC)
            db.commit()
            return True

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
