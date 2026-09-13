from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AssistanceOption, Campaign, Customer, CustomerContact, Obligation


SCENARIOS = [
    ("María López", "premium", "loan", True, False, "1991-04-12"),
    ("Carlos Méndez", "standard", "credit_card", True, True, "1988-11-03"),
    ("Ana Rivera", "new", "mortgage", False, False, "1979-02-24"),
    ("José Hernández", "risk_watch", "personal_loan", True, False, "1995-07-18"),
    ("Lucía Torres", "standard", "auto_loan", False, True, "1984-09-30"),
    ("Rafael Castro", "premium", "credit_card", True, False, "1975-01-06"),
    ("Sofía Aguilar", "new", "loan", False, False, "1999-12-15"),
    ("Diego Pérez", "risk_watch", "personal_loan", True, True, "1990-05-27"),
]


def main() -> None:
    db = SessionLocal()
    try:
        existing = db.scalar(select(Customer).limit(1))
        if existing:
            print("Seed skipped: data already exists.")
            return

        campaign = Campaign(
            name="Cobranza preventiva MVP",
            status="ACTIVE",
            agent_id="demo-agent",
            starts_at=datetime.now(UTC),
            rules_json={"allowed_window": "09:00-17:00", "max_attempts": 2, "preventive_days": 7},
        )
        db.add(campaign)

        today = date.today()
        for index, (name, segment, product, reschedule, insurance, dob) in enumerate(SCENARIOS, start=1):
            customer = Customer(
                external_ref=f"CUS-{index:03d}",
                preferred_name=name,
                dob=dob,
                timezone="America/El_Salvador",
                language="es",
                segment=segment,
                status="ACTIVE",
            )
            db.add(customer)
            db.flush()

            contact = CustomerContact(
                customer_id=customer.id,
                phone_e164=f"+503700000{index:02d}",
                phone_last4=f"00{index:02d}",
                consent_status="OPTED_IN" if index != 7 else "UNKNOWN",
                do_not_call=index == 8,
                is_primary=True,
                preferred_call_window="09:00-17:00",
            )
            db.add(contact)

            obligation = Obligation(
                customer_id=customer.id,
                external_ref=f"OBL-{index:03d}",
                product_type=product,
                next_due_date=today + timedelta(days=3 + index),
                amount_due=Decimal("75.00") + Decimal(index * 23),
                currency="USD",
                status="CURRENT",
            )
            db.add(obligation)
            db.flush()

            option = AssistanceOption(
                obligation_id=obligation.id,
                reschedule_eligible=reschedule,
                earliest_new_date=obligation.next_due_date + timedelta(days=3) if reschedule else None,
                latest_new_date=obligation.next_due_date + timedelta(days=14) if reschedule else None,
                unemployment_insurance_active=insurance,
                insurance_instructions="Escalar a asesor humano para validar cobertura de desempleo." if insurance else "",
            )
            db.add(option)

        db.commit()
        print("Seed completed: synthetic customers loaded.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

