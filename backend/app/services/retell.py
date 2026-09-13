import hashlib
import hmac
import time
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import dob_matches, normalize_dob  # noqa: F401  (normalize_dob se reexporta)
from app.services.audit import resolve_internal_call_id

from app.models import (
    AssistanceOption,
    Call,
    CallJob,
    Customer,
    CustomerAction,
    CustomerContact,
    Obligation,
    VerificationToken,
    WebhookEvent,
)


VERIFICATION_TOKEN_BYTES = 32
RETELL_SIGNATURE_TOLERANCE_SECONDS = 300
VERIFICATION_TOKEN_TTL_SECONDS = 900

def verification_failed_response() -> dict[str, Any]:
    return {"verified": False, "verification_token": None, "message": ""}

def parse_retell_signature(signature: str) -> dict[str, str] | None:
    parts: dict[str, str] = {}
    for item in signature.split(","):
        key, separator, value = item.partition("=")
        if not separator:
            return None
        parts[key.strip()] = value.strip()
    return parts


def build_retell_signature_digest(raw_body: bytes, timestamp: str, api_key: str) -> str:
    return hmac.new(
        api_key.encode("utf-8"),
        raw_body + timestamp.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_retell_signature(raw_body: bytes, signature: str | None) -> bool:
    if not signature:
        return settings.fake_data_only
    if not settings.retell_api_key:
        return False

    parts = parse_retell_signature(signature)
    if not parts:
        return False

    timestamp = parts.get("v")
    received_digest = parts.get("d")
    if not timestamp or not received_digest:
        return False

    try:
        timestamp_seconds = float(timestamp)
    except ValueError:
        return False

    if abs(time.time() - timestamp_seconds) > RETELL_SIGNATURE_TOLERANCE_SECONDS:
        return False

    expected_digest = build_retell_signature_digest(raw_body, timestamp, settings.retell_api_key)
    return hmac.compare_digest(expected_digest, received_digest)


def payload_hash(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def generate_verification_token() -> str:
    return secrets.token_urlsafe(VERIFICATION_TOKEN_BYTES)


def as_utc(value: datetime) -> datetime:
    """SQLite devuelve datetimes naive aunque la columna sea timezone=True."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def issue_verification_token(db: Session, customer_ref: str, retell_call_id: str | None = None) -> str:
    token = generate_verification_token()
    db.add(
        VerificationToken(
            token=token,
            customer_id=customer_ref,
            call_id=resolve_internal_call_id(db, retell_call_id),
            retell_call_id=retell_call_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=VERIFICATION_TOKEN_TTL_SECONDS),
        )
    )
    db.commit()
    return token


def is_verification_token_valid(
    db: Session,
    customer_ref: str,
    verification_token: str,
    retell_call_id: str | None = None,
) -> bool:
    record = db.scalar(select(VerificationToken).where(VerificationToken.token == verification_token))
    if not record or record.customer_id != customer_ref:
        return False
    if as_utc(record.expires_at) <= datetime.now(UTC):
        return False
    # ponytail: la llamada se compara solo cuando ambos lados la conocen. Retell no
    # siempre manda call_id en las Custom Functions, y rechazar por ausencia romperia
    # el flujo real. Upgrade: exigirlo cuando se confirme que el payload lo incluye.
    if record.retell_call_id and retell_call_id and record.retell_call_id != retell_call_id:
        return False
    return True


def verify_identity(
    db: Session,
    customer_ref: str,
    supplied_dob: str,
    retell_call_id: str | None = None,
) -> dict[str, Any]:
    customer = db.scalar(select(Customer).where(Customer.id == customer_ref))
    if not customer:
        return verification_failed_response()

    if not dob_matches(customer.dob_hash, supplied_dob):
        return verification_failed_response()

    return {
        "verified": True,
        "verification_token": issue_verification_token(db, customer.id, retell_call_id),
        "message": "Identidad verificada",
    }


def get_assistance_options(
    db: Session,
    customer_ref: str,
    verification_token: str,
    retell_call_id: str | None = None,
) -> dict[str, Any]:
    if not is_verification_token_valid(db, customer_ref, verification_token, retell_call_id):
        return {"authorized": False, "options": []}

    obligation = db.scalar(select(Obligation).where(Obligation.customer_id == customer_ref).limit(1))
    if not obligation:
        return {"authorized": True, "options": []}

    option = db.scalar(select(AssistanceOption).where(AssistanceOption.obligation_id == obligation.id))
    if not option:
        return {"authorized": True, "options": []}

    return {
        "authorized": True,
        "options": [
            {
                "kind": "reschedule",
                "eligible": option.reschedule_eligible,
                "earliest_new_date": option.earliest_new_date.isoformat() if option.earliest_new_date else None,
                "latest_new_date": option.latest_new_date.isoformat() if option.latest_new_date else None,
            },
            {
                "kind": "unemployment_insurance",
                "eligible": option.unemployment_insurance_active,
                "instructions": option.insurance_instructions,
            },
        ],
    }


def request_reschedule(
    db: Session,
    customer_ref: str,
    verification_token: str,
    proposed_date: str,
    retell_call_id: str | None = None,
) -> dict[str, Any]:
    if not is_verification_token_valid(db, customer_ref, verification_token, retell_call_id):
        return {"accepted": False, "reason": "not_verified"}

    try:
        parsed_proposed_date = date.fromisoformat(proposed_date)
    except (TypeError, ValueError):
        return {"accepted": False, "reason": "invalid_request"}

    obligation = db.scalar(select(Obligation).where(Obligation.customer_id == customer_ref).limit(1))
    call = db.scalar(select(Call).where(Call.customer_id == customer_ref).order_by(Call.created_at.desc()).limit(1))
    if not obligation or not call:
        return {"accepted": False, "reason": "missing_context"}

    action = CustomerAction(
        call_id=call.id,
        obligation_id=obligation.id,
        type="RESCHEDULE_REQUEST",
        proposed_date=parsed_proposed_date,
        status="PENDING_REVIEW",
    )
    db.add(action)
    db.commit()
    return {"accepted": True, "status": "PENDING_REVIEW"}


def build_dynamic_variables(customer: Customer, obligation: Obligation, days_remaining: int) -> dict[str, str]:
    today = datetime.now(ZoneInfo(customer.timezone)).date()
    # ponytail: edad derivada solo del anio de nacimiento, asi que puede quedar
    # 1 alta si el cumpleanios aun no paso. Suficiente para que el agente adapte
    # el tono, y es el precio de no almacenar la fecha completa (ver §2 del plan).
    # Upgrade: si se necesita edad exacta, cifrar dob de forma reversible.
    age = today.year - customer.birth_year
    return {
        "customer_ref": customer.id,
        "obligation_ref": obligation.id,
        "nom_cliente": customer.preferred_name,
        "fecha_pago": obligation.next_due_date.isoformat(),
        "monto_deuda": f"{obligation.amount_due:.2f}",
        "moneda": obligation.currency,
        "dias_restantes_pago": str(days_remaining),
        "nom_producto": obligation.product_type,
        "edad_cliente": str(age),
        "language": customer.language,
        "timezone": customer.timezone,
        # Compatibilidad con el contrato original del guion.
        "preferred_name": customer.preferred_name,
        "next_due_date": obligation.next_due_date.isoformat(),
    }


async def create_retell_call(db: Session, job: CallJob) -> Call:
    contact = db.scalar(select(CustomerContact).where(CustomerContact.customer_id == job.customer_id, CustomerContact.is_primary.is_(True)))
    customer = db.get(Customer, job.customer_id)
    obligation = db.get(Obligation, job.obligation_id)
    call = Call(call_job_id=job.id, customer_id=job.customer_id, status="REGISTERED", outcome="PENDING")
    db.add(call)

    if not customer or not obligation:
        call.status = "BLOCKED"
        call.outcome = "BLOCKED_MISSING_CONTEXT"
        job.status = "BLOCKED"
        job.last_error = "Cliente u obligación inexistente para el trabajo"
        db.commit()
        return call

    # Día calendario del cliente: "vencida" y "días restantes" se definen en su
    # zona horaria, no en UTC ni en el reloj del servidor.
    today = datetime.now(ZoneInfo(customer.timezone)).date()
    days_remaining = (obligation.next_due_date - today).days
    if days_remaining < 0:
        call.status = "BLOCKED"
        call.outcome = "BLOCKED_OVERDUE"
        job.status = "BLOCKED"
        job.last_error = f"Obligación vencida hace {-days_remaining} día(s)"
        db.commit()
        return call

    if not contact or contact.do_not_call or contact.consent_status != "OPTED_IN":
        call.status = "BLOCKED"
        call.outcome = "BLOCKED_BY_CONSENT"
        job.status = "BLOCKED"
        job.last_error = "Cliente sin consentimiento o en lista no llamar"
        db.commit()
        return call

    if contact.phone_e164 not in settings.allowed_numbers:
        call.status = "BLOCKED"
        call.outcome = "BLOCKED_BY_ALLOWLIST"
        job.status = "BLOCKED"
        job.last_error = "Telefono fuera de RETELL_ALLOWED_TEST_NUMBERS"
        db.commit()
        return call

    if not settings.retell_api_key or not settings.retell_agent_id or not settings.retell_from_number:
        call.status = "SIMULATED"
        call.outcome = "SIMULATED_NO_RETELL_CREDENTIALS"
        call.summary = "Llamada simulada: faltan credenciales Retell."
        job.status = "SIMULATED"
        db.commit()
        return call

    payload = {
        "from_number": settings.retell_from_number,
        "to_number": contact.phone_e164,
        "override_agent_id": settings.retell_agent_id,
        "retell_llm_dynamic_variables": build_dynamic_variables(customer, obligation, days_remaining),
        "metadata": {"call_job_id": job.id, "customer_id": customer.id},
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://api.retellai.com/v2/create-phone-call",
            json=payload,
            headers={"Authorization": f"Bearer {settings.retell_api_key}"},
        )
        response.raise_for_status()
        data = response.json()

    call.retell_call_id = data.get("call_id")
    call.raw_payload = data
    job.status = "SENT"
    job.attempt_count += 1
    db.commit()
    db.refresh(call)
    return call


def process_webhook(db: Session, raw_body: bytes, payload: dict[str, Any]) -> dict[str, Any]:
    current_hash = payload_hash(raw_body)
    existing_event = db.scalar(select(WebhookEvent).where(WebhookEvent.payload_hash == current_hash))
    if existing_event:
        return {"ok": True, "duplicate": True}

    event = payload.get("event", "unknown")
    call_payload = payload.get("call") or {}
    if not isinstance(call_payload, dict):
        call_payload = {}

    retell_call_id = call_payload.get("call_id")
    event_record = WebhookEvent(
        retell_call_id=retell_call_id,
        event_type=event,
        payload_hash=current_hash,
        payload_redacted=payload,
        status="RECEIVED",
    )
    db.add(event_record)

    call = db.scalar(select(Call).where(Call.retell_call_id == retell_call_id)) if retell_call_id else None
    if call:
        call_status = call_payload.get("call_status")
        if call_status:
            call.status = str(call_status).upper()

        disconnect_reason = call_payload.get("disconnection_reason")
        if disconnect_reason:
            call.disconnect_reason = disconnect_reason

        transcript = call_payload.get("transcript")
        if transcript:
            call.transcript = transcript

        recording_url = call_payload.get("recording_url")
        if recording_url:
            call.recording_url = recording_url

        analysis = call_payload.get("post_call_analysis_data") or {}
        if not isinstance(analysis, dict):
            analysis = {}

        summary = analysis.get("call_summary")
        if summary:
            call.summary = summary

        sentiment = analysis.get("user_sentiment")
        if sentiment:
            call.sentiment = sentiment

        if "call_successful" in analysis:
            call.call_successful = bool(analysis["call_successful"])
            if call.call_successful:
                call.outcome = "VERIFIED_REMINDER_DELIVERED"

        if event == "call_started":
            call.started_at = datetime.now(UTC)
        if event in {"call_ended", "call_analyzed"}:
            call.ended_at = datetime.now(UTC)

    event_record.status = "PROCESSED"
    event_record.processed_at = datetime.now(UTC)
    db.commit()
    return {"ok": True}
