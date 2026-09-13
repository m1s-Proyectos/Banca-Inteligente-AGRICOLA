from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Call, ToolExecution

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset({"supplied_dob", "dob", "date_of_birth", "verification_token", "phone", "to_number"})


def redact(value: Any) -> Any:
    """Sustituye claves sensibles en cualquier nivel del payload.

    La fecha de nacimiento es el secreto de autenticacion del sistema: no puede
    quedar en el registro de auditoria, que es justo lo que se guarda para
    demostrar cumplimiento.
    """
    if isinstance(value, dict):
        return {key: REDACTED if key in SENSITIVE_KEYS else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def resolve_internal_call_id(db: Session, retell_call_id: str | None) -> str | None:
    if not retell_call_id:
        return None
    return db.scalar(select(Call.id).where(Call.retell_call_id == retell_call_id))


def record_tool_execution(
    db: Session,
    tool_name: str,
    request_payload: Any,
    response_payload: Any,
    started_at: datetime,
    retell_call_id: str | None = None,
    status: str = "OK",
    error_code: str | None = None,
) -> ToolExecution:
    execution = ToolExecution(
        call_id=resolve_internal_call_id(db, retell_call_id),
        retell_call_id=retell_call_id,
        tool_name=tool_name,
        request_redacted=redact(request_payload),
        response_redacted=redact(response_payload),
        started_at=started_at,
        duration_ms=max(0, int((datetime.now(UTC) - started_at).total_seconds() * 1000)),
        status=status,
        error_code=error_code,
    )
    db.add(execution)
    db.commit()
    return execution
