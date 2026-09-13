from fastapi import APIRouter

from app.db.session import DbSession
from app.schemas.dashboard import (
    CallJobOut,
    CallOut,
    DashboardSummary,
    ScheduleCallRequest,
)
from app.services.dashboard import get_summary, list_calls, list_jobs, schedule_call

router = APIRouter(tags=["operations"])


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(db: DbSession) -> DashboardSummary:
    return get_summary(db)


@router.get("/call-jobs", response_model=list[CallJobOut])
def get_call_jobs(db: DbSession) -> list[CallJobOut]:
    return list_jobs(db)


@router.post("/call-jobs", response_model=CallJobOut)
def create_call_job(payload: ScheduleCallRequest, db: DbSession) -> CallJobOut:
    schedule_call(db, payload.customer_id, payload.obligation_id, payload.scheduled_at)
    return list_jobs(db)[0]


@router.get("/calls", response_model=list[CallOut])
def get_calls(db: DbSession) -> list[CallOut]:
    return list_calls(db)

