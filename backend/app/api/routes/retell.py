import time
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.core.config import settings
from app.db.session import DbSession
from app.schemas.dashboard import ToolExecutionOut, WebhookEventOut
from app.services.audit import record_tool_execution
from app.services.dashboard import list_tool_executions, list_webhook_events
from app.services.retell import (
    create_retell_web_call,
    get_assistance_options,
    process_webhook,
    request_reschedule,
    verify_identity,
    verify_retell_signature,
)

router = APIRouter(tags=["retell"])
WEB_CALL_COOLDOWN_SECONDS = 10
_last_web_call_at = 0.0


class WebCallRequest(BaseModel):
    customer_id: str
    obligation_id: str


def extract_retell_args(body: dict) -> dict:
    args = body.get("args")
    return args if isinstance(args, dict) else body


def extract_retell_call_id(body: dict) -> str | None:
    """Retell manda la llamada en `call.call_id`; algunos flujos la ponen plana."""
    call = body.get("call")
    if isinstance(call, dict) and call.get("call_id"):
        return str(call["call_id"])
    call_id = body.get("call_id")
    return str(call_id) if call_id else None


@router.post("/web-calls")
async def create_web_call(payload: WebCallRequest, db: DbSession) -> dict[str, Any]:
    global _last_web_call_at
    if not settings.fake_data_only:
        raise HTTPException(status_code=403, detail="Web call demo is disabled")

    now = time.monotonic()
    # ponytail: un solo proceso Render y cooldown global bastan para el MVP.
    # Techo: no coordina réplicas; migrar a auth + rate limit compartido antes de producción.
    if now - _last_web_call_at < WEB_CALL_COOLDOWN_SECONDS:
        raise HTTPException(status_code=429, detail="Espere unos segundos antes de iniciar otra llamada")
    _last_web_call_at = now

    try:
        return await create_retell_web_call(db, payload.customer_id, payload.obligation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Retell no pudo crear la llamada web") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/webhooks")
async def retell_webhook(
    request: Request,
    db: DbSession,
    x_retell_signature: Annotated[str | None, Header()] = None,
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    try:
        payload = await request.json()
    except ValueError:
        return {"ok": False, "error": "invalid_payload"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "invalid_payload"}
    return process_webhook(db, raw_body, payload)


@router.post("/tools/verify-identity")
async def tool_verify_identity(
    request: Request,
    db: DbSession,
    x_retell_signature: Annotated[str | None, Header()] = None,
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    body = await request.json()
    args = extract_retell_args(body)
    retell_call_id = extract_retell_call_id(body)
    started_at = datetime.now(UTC)
    customer_ref = args.get("customer_ref")
    supplied_dob = args.get("supplied_dob")
    if not customer_ref or not supplied_dob:
        result = {"verified": False, "verification_token": None, "message": ""}
        error_code = "missing_fields"
    else:
        result = verify_identity(db, customer_ref, supplied_dob, retell_call_id)
        error_code = None if result["verified"] else "not_verified"
    record_tool_execution(
        db,
        tool_name="verify_identity",
        request_payload=args,
        response_payload=result,
        started_at=started_at,
        retell_call_id=retell_call_id,
        status="OK" if error_code is None else "REJECTED",
        error_code=error_code,
    )
    return result


@router.post("/tools/get-assistance-options")
async def tool_get_assistance_options(
    request: Request,
    db: DbSession,
    x_retell_signature: Annotated[str | None, Header()] = None,
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    body = await request.json()
    args = extract_retell_args(body)
    retell_call_id = extract_retell_call_id(body)
    started_at = datetime.now(UTC)
    customer_ref = args.get("customer_ref")
    verification_token = args.get("verification_token")
    obligation_ref = args.get("obligation_ref")
    if not customer_ref or not verification_token:
        result = {"authorized": False, "options": []}
        error_code = "missing_fields"
    else:
        result = get_assistance_options(
            db,
            customer_ref,
            verification_token,
            retell_call_id=retell_call_id,
            obligation_ref=obligation_ref,
        )
        error_code = None if result["authorized"] else "not_verified"
    record_tool_execution(
        db,
        tool_name="get_assistance_options",
        request_payload=args,
        response_payload=result,
        started_at=started_at,
        retell_call_id=retell_call_id,
        status="OK" if error_code is None else "REJECTED",
        error_code=error_code,
    )
    return result


@router.post("/tools/request-reschedule")
async def tool_request_reschedule(
    request: Request,
    db: DbSession,
    x_retell_signature: Annotated[str | None, Header()] = None,
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    body = await request.json()
    args = extract_retell_args(body)
    retell_call_id = extract_retell_call_id(body)
    started_at = datetime.now(UTC)
    customer_ref = args.get("customer_ref")
    verification_token = args.get("verification_token")
    proposed_date = args.get("proposed_date")
    obligation_ref = args.get("obligation_ref")
    if not customer_ref or not verification_token or not proposed_date:
        result = {"accepted": False, "reason": "invalid_request"}
    else:
        result = request_reschedule(
            db,
            customer_ref,
            verification_token,
            proposed_date,
            retell_call_id=retell_call_id,
            obligation_ref=obligation_ref,
        )
    record_tool_execution(
        db,
        tool_name="request_reschedule",
        request_payload=args,
        response_payload=result,
        started_at=started_at,
        retell_call_id=retell_call_id,
        status="OK" if result["accepted"] else "REJECTED",
        error_code=None if result["accepted"] else result.get("reason"),
    )
    return result


@router.get("/tool-executions", response_model=list[ToolExecutionOut])
def get_tool_executions(db: DbSession) -> list[ToolExecutionOut]:
    return list_tool_executions(db)


@router.get("/webhook-events", response_model=list[WebhookEventOut])
def get_webhook_events(db: DbSession) -> list[WebhookEventOut]:
    return list_webhook_events(db)
