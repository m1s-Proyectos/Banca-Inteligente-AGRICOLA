from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ObligationOut(BaseModel):
    id: str
    product_type: str
    next_due_date: date
    # Dias restantes calculados en la zona horaria del cliente, no en UTC: en
    # cobranza preventiva "vence manana" cambia de significado al cruzar el dia.
    days_to_due: int
    amount_due: Decimal
    currency: str
    status: str
    # Lo que el agente puede ofrecer en la llamada. Vive en assistance_options
    # y hasta ahora solo lo veia Retell, nunca el operador humano.
    reschedule_eligible: bool = False
    earliest_new_date: date | None = None
    latest_new_date: date | None = None
    unemployment_insurance_active: bool = False
    # Historial de pago de ciclos anteriores. total = 0 significa sin medicion.
    on_time_payments: int = 0
    total_payments: int = 0


class CustomerOut(BaseModel):
    id: str
    external_ref: str
    preferred_name: str
    # Solo el anio: la fecha completa nunca se almacena en claro (ver
    # migracion 0002_pii_audit_payments). La edad exacta no es derivable.
    birth_year: int
    timezone: str
    language: str
    segment: str
    status: str
    cohort: str
    phone_last4: str | None
    do_not_call: bool
    consent_status: str | None
    preferred_call_window: str | None
    last_call_at: datetime | None = None
    last_call_outcome: str | None = None
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


class ToolExecutionOut(BaseModel):
    id: str
    retell_call_id: str | None
    tool_name: str
    started_at: datetime
    duration_ms: int
    status: str
    error_code: str | None
    request_redacted: dict
    response_redacted: dict


class WebhookEventOut(BaseModel):
    id: str
    retell_call_id: str | None
    event_type: str
    received_at: datetime
    processed_at: datetime | None
    status: str
    error: str | None


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
