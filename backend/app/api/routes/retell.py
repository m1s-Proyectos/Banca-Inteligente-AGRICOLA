from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.retell import (
    get_assistance_options,
    process_webhook,
    request_reschedule,
    verify_identity,
    verify_retell_signature,
)

router = APIRouter(tags=["retell"])


@router.post("/webhooks")
async def retell_webhook(
    request: Request,
    x_retell_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    payload = await request.json()
    return process_webhook(db, raw_body, payload)


@router.post("/tools/verify-identity")
async def tool_verify_identity(
    request: Request,
    x_retell_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    body = await request.json()
    args = body.get("args", body)
    return verify_identity(db, args["customer_ref"], args["supplied_dob"])


@router.post("/tools/get-assistance-options")
async def tool_get_assistance_options(
    request: Request,
    x_retell_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    body = await request.json()
    args = body.get("args", body)
    return get_assistance_options(db, args["customer_ref"], args["verification_token"])


@router.post("/tools/request-reschedule")
async def tool_request_reschedule(
    request: Request,
    x_retell_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    raw_body = await request.body()
    if not verify_retell_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    body = await request.json()
    args = body.get("args", body)
    return request_reschedule(db, args["customer_ref"], args["verification_token"], args["proposed_date"])

