from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ObligationOut(BaseModel):
    id: str
    product_type: str
    next_due_date: date
    amount_due: Decimal
    currency: str
    status: str


class CustomerOut(BaseModel):
    id: str
    external_ref: str
    preferred_name: str
    timezone: str
    language: str
    segment: str
    status: str
    phone_last4: str | None
    do_not_call: bool
    obligations: list[ObligationOut]


class ScheduleCallRequest(BaseModel):
    customer_id: str
    obligation_id: str
    scheduled_at: datetime | None = None


class CallJobOut(BaseModel):
    id: str
    customer_name: str
    obligation_product: str
    scheduled_at: datetime
    status: str
    attempt_count: int
    last_error: str | None


class CallOut(BaseModel):
    id: str
    customer_name: str
    status: str
    outcome: str
    sentiment: str | None
    summary: str | None
    transcript: str | None
    recording_url: str | None
    created_at: datetime


class DashboardSummary(BaseModel):
    customers: int
    obligations: int
    pending_jobs: int
    attempted_calls: int
    successful_calls: int
    blocked_calls: int
    # Resultado, no actividad: pago puntual del grupo llamado contra el control.
    on_time_rate_treatment: float | None = None
    on_time_rate_control: float | None = None

