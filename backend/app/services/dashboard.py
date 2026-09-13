from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import (
    Call,
    CallJob,
    Campaign,
    Customer,
    Obligation,
    PaymentOutcome,
    ToolExecution,
    WebhookEvent,
)
from app.schemas.dashboard import (
    CallJobOut,
    CallOut,
    CustomerOut,
    DashboardSummary,
    ObligationOut,
    ToolExecutionOut,
    WebhookEventOut,
)


def get_or_create_demo_campaign(db: Session) -> Campaign:
    campaign = db.scalar(select(Campaign).where(Campaign.name == "Cobranza preventiva MVP"))
    if campaign:
        return campaign

    campaign = Campaign(
        name="Cobranza preventiva MVP",
        status="ACTIVE",
        agent_id=settings.retell_agent_id or "demo-agent",
        rules_json={
            "max_attempts": 2,
            "allowed_window": "09:00-17:00",
            "fake_data_only": settings.fake_data_only,
        },
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def today_for(timezone: str) -> date:
    """Fecha de hoy en la zona del cliente.

    Los dias restantes hasta el vencimiento se cuentan desde el calendario del
    cliente: a las 20:00 de El Salvador ya es el dia siguiente en UTC, y un
    recordatorio preventivo que dice "vence en 2 dias" en vez de 3 pierde
    credibilidad. Cae a UTC si la zona guardada no existe en la tzdata del host.
    """
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
    return datetime.now(zone).date()


def list_customers(db: Session) -> list[CustomerOut]:
    customers = db.scalars(
        select(Customer)
        .options(
            selectinload(Customer.contacts),
            selectinload(Customer.obligations).selectinload(Obligation.assistance_options),
        )
        .order_by(Customer.preferred_name)
    ).all()

    # Dos agregados sueltos en vez de una consulta por cliente: con N clientes
    # el panel hacia 2N+1 viajes a la base.
    payments = {
        row.obligation_id: (row.on_time, row.total)
        for row in db.execute(
            select(
                PaymentOutcome.obligation_id,
                func.count(PaymentOutcome.id).label("total"),
                func.sum(case((PaymentOutcome.status == "ON_TIME", 1), else_=0)).label("on_time"),
            ).group_by(PaymentOutcome.obligation_id)
        )
    }

    # row_number en vez de max(created_at): necesitamos el outcome de esa misma
    # fila, y un max() por separado se puede aparear con la llamada equivocada
    # cuando dos comparten timestamp.
    ranked_calls = (
        select(
            Call.customer_id,
            Call.created_at,
            Call.outcome,
            func.row_number()
            .over(partition_by=Call.customer_id, order_by=Call.created_at.desc())
            .label("rank"),
        )
        .subquery()
    )
    last_calls = {
        row.customer_id: row for row in db.execute(select(ranked_calls).where(ranked_calls.c.rank == 1))
    }

    output = []
    for customer in customers:
        primary = next((contact for contact in customer.contacts if contact.is_primary), None)
        today = today_for(customer.timezone)
        last_call = last_calls.get(customer.id)
        output.append(
            CustomerOut(
                id=customer.id,
                external_ref=customer.external_ref,
                preferred_name=customer.preferred_name,
                birth_year=customer.birth_year,
                timezone=customer.timezone,
                language=customer.language,
                segment=customer.segment,
                status=customer.status,
                cohort=customer.cohort,
                phone_last4=primary.phone_last4 if primary else None,
                do_not_call=primary.do_not_call if primary else False,
                consent_status=primary.consent_status if primary else None,
                preferred_call_window=primary.preferred_call_window if primary else None,
                last_call_at=last_call.created_at if last_call else None,
                last_call_outcome=last_call.outcome if last_call else None,
                obligations=[
                    ObligationOut(
                        id=item.id,
                        product_type=item.product_type,
                        next_due_date=item.next_due_date,
                        days_to_due=(item.next_due_date - today).days,
                        amount_due=item.amount_due,
                        currency=item.currency,
                        status=item.status,
                        reschedule_eligible=any(o.reschedule_eligible for o in item.assistance_options),
                        earliest_new_date=next(
                            (o.earliest_new_date for o in item.assistance_options if o.earliest_new_date), None
                        ),
                        latest_new_date=next(
                            (o.latest_new_date for o in item.assistance_options if o.latest_new_date), None
                        ),
                        unemployment_insurance_active=any(
                            o.unemployment_insurance_active for o in item.assistance_options
                        ),
                        on_time_payments=payments.get(item.id, (0, 0))[0] or 0,
                        total_payments=payments.get(item.id, (0, 0))[1] or 0,
                    )
                    for item in customer.obligations
                ],
            )
        )
    return output


def schedule_call(db: Session, customer_id: str, obligation_id: str, scheduled_at: datetime | None) -> CallJob:
    campaign = get_or_create_demo_campaign(db)
    job = CallJob(
        campaign_id=campaign.id,
        customer_id=customer_id,
        obligation_id=obligation_id,
        scheduled_at=scheduled_at or datetime.now(UTC),
        status="PENDING",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_jobs(db: Session) -> list[CallJobOut]:
    jobs = db.scalars(
        select(CallJob)
        .options(selectinload(CallJob.customer), selectinload(CallJob.obligation))
        .order_by(CallJob.scheduled_at.desc())
        .limit(50)
    ).all()
    return [
        CallJobOut(
            id=job.id,
            customer_name=job.customer.preferred_name,
            obligation_product=job.obligation.product_type,
            scheduled_at=job.scheduled_at,
            status=job.status,
            attempt_count=job.attempt_count,
            last_error=job.last_error,
        )
        for job in jobs
    ]


def list_calls(db: Session) -> list[CallOut]:
    calls = db.scalars(select(Call).options(selectinload(Call.customer)).order_by(Call.created_at.desc()).limit(50)).all()
    return [
        CallOut(
            id=call.id,
            customer_name=call.customer.preferred_name,
            status=call.status,
            outcome=call.outcome,
            sentiment=call.sentiment,
            duration_ms=call.duration_ms,
            summary=call.summary,
            transcript=call.transcript,
            recording_url=call.recording_url,
            created_at=call.created_at,
        )
        for call in calls
    ]


def list_tool_executions(db: Session, limit: int = 50) -> list[ToolExecutionOut]:
    """Auditoria de las Custom Functions que invoco el agente.

    request_redacted nunca trae la fecha de nacimiento ni el token, asi que es
    seguro exponerla al panel tal como se guardo.
    """
    rows = db.scalars(select(ToolExecution).order_by(ToolExecution.started_at.desc()).limit(limit)).all()
    return [
        ToolExecutionOut(
            id=row.id,
            retell_call_id=row.retell_call_id,
            tool_name=row.tool_name,
            started_at=row.started_at,
            duration_ms=row.duration_ms,
            status=row.status,
            error_code=row.error_code,
            request_redacted=row.request_redacted or {},
            response_redacted=row.response_redacted or {},
        )
        for row in rows
    ]


def list_webhook_events(db: Session, limit: int = 50) -> list[WebhookEventOut]:
    rows = db.scalars(select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(limit)).all()
    return [
        WebhookEventOut(
            id=row.id,
            retell_call_id=row.retell_call_id,
            event_type=row.event_type,
            received_at=row.received_at,
            processed_at=row.processed_at,
            status=row.status,
            error=row.error,
        )
        for row in rows
    ]


def on_time_payment_rate(db: Session, cohort: str) -> float | None:
    """Proporcion de obligaciones pagadas en fecha para una cohorte.

    Devuelve None en vez de 0 cuando no hay datos, para que el panel distingue
    "sin medicion" de "nadie pago".
    """
    base = (
        select(func.count(PaymentOutcome.id))
        .join(Obligation, PaymentOutcome.obligation_id == Obligation.id)
        .join(Customer, Obligation.customer_id == Customer.id)
        .where(Customer.cohort == cohort)
    )
    total = db.scalar(base) or 0
    if not total:
        return None
    on_time = db.scalar(base.where(PaymentOutcome.status == "ON_TIME")) or 0
    return round(on_time / total, 4)


def get_summary(db: Session) -> DashboardSummary:
    return DashboardSummary(
        customers=db.scalar(select(func.count(Customer.id))) or 0,
        obligations=db.scalar(select(func.count(Obligation.id))) or 0,
        pending_jobs=db.scalar(select(func.count(CallJob.id)).where(CallJob.status == "PENDING")) or 0,
        attempted_calls=db.scalar(select(func.count(Call.id))) or 0,
        successful_calls=db.scalar(select(func.count(Call.id)).where(Call.call_successful.is_(True))) or 0,
        blocked_calls=db.scalar(select(func.count(Call.id)).where(Call.outcome == "BLOCKED_BY_ALLOWLIST")) or 0,
        on_time_rate_treatment=on_time_payment_rate(db, "TREATMENT"),
        on_time_rate_control=on_time_payment_rate(db, "CONTROL"),
    )
