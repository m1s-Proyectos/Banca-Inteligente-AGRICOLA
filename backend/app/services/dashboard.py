from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import Call, CallJob, Campaign, Customer, CustomerContact, Obligation
from app.schemas.dashboard import CallJobOut, CallOut, CustomerOut, DashboardSummary, ObligationOut


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


def list_customers(db: Session) -> list[CustomerOut]:
    customers = db.scalars(
        select(Customer)
        .options(selectinload(Customer.contacts), selectinload(Customer.obligations))
        .order_by(Customer.preferred_name)
    ).all()
    output = []
    for customer in customers:
        primary = next((contact for contact in customer.contacts if contact.is_primary), None)
        output.append(
            CustomerOut(
                id=customer.id,
                external_ref=customer.external_ref,
                preferred_name=customer.preferred_name,
                timezone=customer.timezone,
                language=customer.language,
                segment=customer.segment,
                status=customer.status,
                phone_last4=primary.phone_last4 if primary else None,
                do_not_call=primary.do_not_call if primary else False,
                obligations=[
                    ObligationOut(
                        id=item.id,
                        product_type=item.product_type,
                        next_due_date=item.next_due_date,
                        amount_due=item.amount_due,
                        currency=item.currency,
                        status=item.status,
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
            summary=call.summary,
            transcript=call.transcript,
            recording_url=call.recording_url,
            created_at=call.created_at,
        )
        for call in calls
    ]


def get_summary(db: Session) -> DashboardSummary:
    return DashboardSummary(
        customers=db.scalar(select(func.count(Customer.id))) or 0,
        obligations=db.scalar(select(func.count(Obligation.id))) or 0,
        pending_jobs=db.scalar(select(func.count(CallJob.id)).where(CallJob.status == "PENDING")) or 0,
        attempted_calls=db.scalar(select(func.count(Call.id))) or 0,
        successful_calls=db.scalar(select(func.count(Call.id)).where(Call.call_successful.is_(True))) or 0,
        blocked_calls=db.scalar(select(func.count(Call.id)).where(Call.outcome == "BLOCKED_BY_ALLOWLIST")) or 0,
    )

