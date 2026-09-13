import hashlib
import hmac
import secrets
import time
from datetime import UTC, date, datetime
from typing import Any

import httpx
from app.core.config import settings
from app.models import (
    AssistanceOption,
    Call,
    CallJob,
    Customer,
    CustomerAction,
    CustomerContact,
    Obligation,
    WebhookEvent,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

RETELL_SIGNATURE_TOLERANCE_SECONDS = 300
# Token de verificación sin estado (HMAC): sobrevive reinicios de la API y
# funciona con varias réplicas; expira solo a los 30 minutos.
# ponytail: no se puede revocar antes de expirar; upgrade: tabla de tokens con revocación.
VERIFICATION_TOKEN_TTL_SECONDS = 30 * 60

MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

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


def normalize_dob(value: str) -> str:
    return value.strip().replace("/", "-")


def age_from_dob(dob: str) -> int | None:
    try:
        born = date.fromisoformat(normalize_dob(dob))
    except ValueError:
        return None
    today = datetime.now(UTC).date()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def speakable_date(value: date) -> str:
    return f"{value.day} de {MONTHS_ES[value.month - 1]} de {value.year}"


def resolve_obligation(db: Session, customer_ref: str, obligation_ref: str | None) -> Obligation | None:
    stmt = select(Obligation).where(Obligation.customer_id == customer_ref)
    if obligation_ref:
        stmt = stmt.where(Obligation.id == obligation_ref)
    return db.scalar(stmt.limit(1))


def issue_verification_token(customer_ref: str) -> str:
    expires = str(int(time.time()) + VERIFICATION_TOKEN_TTL_SECONDS)
    nonce = secrets.token_hex(8)
    digest = _verification_token_digest(customer_ref, expires, nonce)
    return f"{expires}.{nonce}.{digest}"


def _verification_token_digest(customer_ref: str, expires: str, nonce: str) -> str:
    message = f"{customer_ref}|{expires}|{nonce}".encode()
    return hmac.new(settings.app_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def is_verification_token_valid(customer_ref: str, verification_token: str) -> bool:
    parts = verification_token.split(".") if isinstance(verification_token, str) else []
    if len(parts) != 3:
        return False
    expires, nonce, digest = parts
    if not expires.isdigit() or time.time() > float(expires):
        return False
    return hmac.compare_digest(_verification_token_digest(customer_ref, expires, nonce), digest)


def verify_identity(db: Session, customer_ref: str, supplied_dob: str) -> dict[str, Any]:
    customer = db.scalar(select(Customer).where(Customer.id == customer_ref))
    if not customer:
        return verification_failed_response()

    verified = normalize_dob(customer.dob) == normalize_dob(supplied_dob)
    if not verified:
        return verification_failed_response()

    return {
        "verified": True,
        "verification_token": issue_verification_token(customer.id),
        "message": "Identidad verificada",
    }


def get_assistance_options(
    db: Session, customer_ref: str, verification_token: str, obligation_ref: str | None = None
) -> dict[str, Any]:
    if not is_verification_token_valid(customer_ref, verification_token):
        return {"authorized": False, "options": []}

    obligation = resolve_obligation(db, customer_ref, obligation_ref)
    if not obligation:
        return {"authorized": True, "options": []}

    option = db.scalar(select(AssistanceOption).where(AssistanceOption.obligation_id == obligation.id))
    if not option:
        return {"authorized": True, "options": []}

    # Solo se listan opciones activas y cada una lleva texto aprobado para leerlo
    # tal cual (guardrail #3 del guion: no mencionar ni inventar opciones no provistas;
    # una opción inactiva simplemente no aparece).
    options: list[dict[str, Any]] = []
    if option.reschedule_eligible and option.earliest_new_date and option.latest_new_date:
        options.append(
            {
                "kind": "reschedule",
                "text": (
                    "Reprogramación del pago: puede elegir una nueva fecha entre el "
                    f"{speakable_date(option.earliest_new_date)} y el {speakable_date(option.latest_new_date)}."
                ),
            }
        )
    if option.unemployment_insurance_active and option.insurance_instructions:
        options.append({"kind": "unemployment_insurance", "text": option.insurance_instructions})

    return {"authorized": True, "options": options}


def request_reschedule(
    db: Session, customer_ref: str, verification_token: str, proposed_date: str, obligation_ref: str | None = None
) -> dict[str, Any]:
    if not is_verification_token_valid(customer_ref, verification_token):
        return {"accepted": False, "reason": "not_verified"}

    try:
        parsed_proposed_date = date.fromisoformat(proposed_date)
    except (TypeError, ValueError):
        return {"accepted": False, "reason": "invalid_request"}

    obligation = resolve_obligation(db, customer_ref, obligation_ref)
    call = db.scalar(select(Call).where(Call.customer_id == customer_ref).order_by(Call.created_at.desc()).limit(1))
    if not obligation or not call:
        return {"accepted": False, "reason": "missing_context"}

    option = db.scalar(select(AssistanceOption).where(AssistanceOption.obligation_id == obligation.id))
    if not option or not option.reschedule_eligible or not option.earliest_new_date or not option.latest_new_date:
        return {"accepted": False, "reason": "not_eligible"}

    # Frontera de confianza: el rango de fechas se valida en el backend,
    # no solo en el prompt del agente.
    if not option.earliest_new_date <= parsed_proposed_date <= option.latest_new_date:
        return {
            "accepted": False,
            "reason": "out_of_range",
            "earliest_new_date": option.earliest_new_date.isoformat(),
            "latest_new_date": option.latest_new_date.isoformat(),
        }

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
    """Variables que interpola el prompt del agente. Retell exige valores string."""
    age = age_from_dob(customer.dob)
    return {
        # Claves técnicas: las consumen las custom functions de Retell.
        "customer_ref": customer.id,
        "obligation_ref": obligation.id,
        "language": customer.language,
        "timezone": customer.timezone,
        # Claves del guion (nombres en español que interpola el prompt).
        "nom_cliente": customer.preferred_name,
        "fecha_pago": obligation.next_due_date.isoformat(),
        "monto_deuda": f"{obligation.amount_due:.2f}",
        "moneda": obligation.currency,
        "dias_restantes_pago": str(days_remaining),
        "nom_producto": obligation.product_type,
        "edad_cliente": str(age) if age is not None else "",
        # Compatibilidad con el contrato original; eliminar cuando el agente
        # de Retell consuma únicamente las claves en español.
        "preferred_name": customer.preferred_name,
        "next_due_date": obligation.next_due_date.isoformat(),
    }


async def create_retell_call(db: Session, job: CallJob) -> Call:
    contact = db.scalar(select(CustomerContact).where(CustomerContact.customer_id == job.customer_id, CustomerContact.is_primary.is_(True)))
    customer = db.get(Customer, job.customer_id)
    obligation = db.get(Obligation, job.obligation_id)
    call = Call(call_job_id=job.id, customer_id=job.customer_id, status="REGISTERED", outcome="PENDING")
    db.add(call)

    def block(outcome: str, last_error: str) -> Call:
        call.status = "BLOCKED"
        call.outcome = outcome
        job.status = "BLOCKED"
        job.last_error = last_error
        db.commit()
        return call

    if not customer or not obligation:
        return block("BLOCKED_MISSING_CONTEXT", "Cliente u obligación inexistente para el trabajo")

    days_remaining = (obligation.next_due_date - datetime.now(UTC).date()).days
    if days_remaining < 0:
        # Guardrail del guion: el flujo preventivo solo aplica con {{dias_restantes_pago}} >= 0.
        return block("BLOCKED_OVERDUE", "Obligación vencida: corresponde al flujo de cobranza vencida")

    if not contact or contact.do_not_call or contact.consent_status != "OPTED_IN":
        return block("BLOCKED_BY_CONSENT", "Cliente sin consentimiento o en lista no llamar")

    if contact.phone_e164 not in settings.allowed_numbers:
        return block("BLOCKED_BY_ALLOWLIST", "Telefono fuera de RETELL_ALLOWED_TEST_NUMBERS")

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
