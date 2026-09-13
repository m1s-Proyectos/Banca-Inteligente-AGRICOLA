import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    external_ref: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    preferred_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dob_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    birth_year: Mapped[int] = mapped_column(Integer, nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    segment: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="ACTIVE")
    cohort: Mapped[str] = mapped_column(String(20), nullable=False, default="TREATMENT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    contacts: Mapped[list["CustomerContact"]] = relationship(back_populates="customer", cascade="all, delete-orphan")
    obligations: Mapped[list["Obligation"]] = relationship(back_populates="customer", cascade="all, delete-orphan")


class CustomerContact(Base):
    __tablename__ = "customer_contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(32), nullable=False)
    phone_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    consent_status: Mapped[str] = mapped_column(String(40), nullable=False)
    do_not_call: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preferred_call_window: Mapped[str] = mapped_column(String(80), nullable=False, default="09:00-17:00")

    customer: Mapped[Customer] = relationship(back_populates="contacts")


class Obligation(Base):
    __tablename__ = "obligations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    product_type: Mapped[str] = mapped_column(String(80), nullable=False)
    next_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="CURRENT")

    customer: Mapped[Customer] = relationship(back_populates="obligations")
    assistance_options: Mapped[list["AssistanceOption"]] = relationship(back_populates="obligation", cascade="all, delete-orphan")


class AssistanceOption(Base):
    __tablename__ = "assistance_options"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    obligation_id: Mapped[str] = mapped_column(ForeignKey("obligations.id"), nullable=False)
    reschedule_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    earliest_new_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    latest_new_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    unemployment_insurance_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    insurance_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")

    obligation: Mapped[Obligation] = relationship(back_populates="assistance_options")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="ACTIVE")
    agent_id: Mapped[str] = mapped_column(String(120), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rules_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class CallJob(Base):
    __tablename__ = "call_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    obligation_id: Mapped[str] = mapped_column(ForeignKey("obligations.id"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    customer: Mapped[Customer] = relationship()
    obligation: Mapped[Obligation] = relationship()
    campaign: Mapped[Campaign] = relationship()


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    call_job_id: Mapped[str] = mapped_column(ForeignKey("call_jobs.id"), nullable=False)
    retell_call_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="REGISTERED")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disconnect_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    right_party_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reminder_delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    call_successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sentiment: Mapped[str | None] = mapped_column(String(80), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String(80), nullable=False, default="PENDING")
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job: Mapped[CallJob] = relationship()
    customer: Mapped[Customer] = relationship()


class CustomerAction(Base):
    __tablename__ = "customer_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), nullable=False)
    obligation_id: Mapped[str] = mapped_column(ForeignKey("obligations.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    proposed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    retell_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    payload_redacted: Mapped[dict] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="RECEIVED")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)



class VerificationToken(Base):
    """Token emitido tras verificar identidad.

    Vive en la base y no en memoria del proceso para que sobreviva a reinicios,
    funcione con mas de un worker de uvicorn y deje evidencia auditable de que
    la verificacion ocurrio antes de revelar informacion financiera.
    """

    __tablename__ = "verification_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    call_id: Mapped[str | None] = mapped_column(ForeignKey("calls.id"), nullable=True)
    retell_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ToolExecution(Base):
    """Registro de cada Custom Function invocada por Retell.

    Es la evidencia de que la informacion complementaria solo se consulto
    despues de verificar identidad. `request_redacted` nunca contiene la fecha
    de nacimiento ni el token.
    """

    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    call_id: Mapped[str | None] = mapped_column(ForeignKey("calls.id"), nullable=True)
    retell_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    request_redacted: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    response_redacted: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="OK")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class PaymentOutcome(Base):
    """Resultado de pago de una obligacion, para medir pago puntual.

    Sin esta tabla el panel solo puede medir actividad (llamadas hechas) en vez
    de resultado (si el cliente pago a tiempo), que es la metrica que el plan
    define como impacto principal.
    """

    __tablename__ = "payment_outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    obligation_id: Mapped[str] = mapped_column(ForeignKey("obligations.id"), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_paid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_batch_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
