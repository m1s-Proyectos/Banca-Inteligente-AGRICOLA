from fastapi import APIRouter, Header, HTTPException, Request

from app.db.session import DbSession
from app.services.retell import (
    get_assistance_options,
    process_webhook,
    request_reschedule,
    verify_identity,
    verify_retell_signature,
)

router = APIRouter(tags=["retell"])


def extract_retell_args(body: dict) -> dict:
    args = body.get("args")
    return args if isinstance(args, dict) else body


@router.post("/webhooks")
async def retell_webhook(
    request: Request,
    db: DbSession,
    x_retell_signature: str | None = Header(default=None),
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
    x_retell_signature: str | None = Header(default=None),
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    body = await request.json()
    args = extract_retell_args(body)
    customer_ref = args.get("customer_ref")
    supplied_dob = args.get("supplied_dob")
    if not customer_ref or not supplied_dob:
        return {"verified": False, "verification_token": None, "message": ""}
    return verify_identity(db, customer_ref, supplied_dob)


@router.post("/tools/get-assistance-options")
async def tool_get_assistance_options(
    request: Request,
    db: DbSession,
    x_retell_signature: str | None = Header(default=None),
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    body = await request.json()
    args = extract_retell_args(body)
    customer_ref = args.get("customer_ref")
    verification_token = args.get("verification_token")
    obligation_ref = args.get("obligation_ref")
    if not customer_ref or not verification_token:
        return {"authorized": False, "options": []}
    return get_assistance_options(db, customer_ref, verification_token, obligation_ref)


@router.post("/tools/request-reschedule")
async def tool_request_reschedule(
    request: Request,
    db: DbSession,
    x_retell_signature: str | None = Header(default=None),
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    body = await request.json()
    args = extract_retell_args(body)
    customer_ref = args.get("customer_ref")
    verification_token = args.get("verification_token")
    proposed_date = args.get("proposed_date")
    obligation_ref = args.get("obligation_ref")
    if not customer_ref or not verification_token or not proposed_date:
        return {"accepted": False, "reason": "invalid_request"}
    return request_reschedule(db, customer_ref, verification_token, proposed_date, obligation_ref)

