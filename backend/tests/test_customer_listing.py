import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.security import hash_dob
from app.db.base import Base
from app.models import (
    AssistanceOption,
    Call,
    CallJob,
    Campaign,
    Customer,
    CustomerContact,
    Obligation,
    PaymentOutcome,
)
from app.services.dashboard import list_customers

TZ = "America/El_Salvador"


class CustomerListingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.today = datetime.now(ZoneInfo(TZ)).date()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def seed(self) -> Obligation:
        customer = Customer(
            external_ref="CUS-001",
            preferred_name="Lucia Torres",
            dob_hash=hash_dob("1984-09-30"),
            birth_year=1984,
            timezone=TZ,
            language="es",
            segment="standard",
            status="ACTIVE",
            cohort="CONTROL",
        )
        self.db.add(customer)
        self.db.flush()

        self.db.add(
            CustomerContact(
                customer_id=customer.id,
                phone_e164="+50370000001",
                phone_last4="0001",
                consent_status="UNKNOWN",
                do_not_call=False,
                is_primary=True,
                preferred_call_window="10:00-16:00",
            )
        )

        obligation = Obligation(
            customer_id=customer.id,
            external_ref="OBL-001",
            product_type="auto_loan",
            next_due_date=self.today + timedelta(days=5),
            amount_due=Decimal("190.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(obligation)
        self.db.flush()

        self.db.add(
            AssistanceOption(
                obligation_id=obligation.id,
                reschedule_eligible=True,
                earliest_new_date=obligation.next_due_date + timedelta(days=3),
                latest_new_date=obligation.next_due_date + timedelta(days=14),
                unemployment_insurance_active=True,
                insurance_instructions="Escalar a asesor humano.",
            )
        )
        for status in ("ON_TIME", "ON_TIME", "LATE"):
            self.db.add(
                PaymentOutcome(
                    obligation_id=obligation.id,
                    due_date=self.today - timedelta(days=30),
                    paid_at=self.today - timedelta(days=30),
                    amount_paid=Decimal("190.00"),
                    status=status,
                    source_batch_id="test",
                )
            )
        self.db.commit()
        return obligation

    def add_call(self, obligation: Obligation, outcome: str, created_at: datetime) -> None:
        campaign = Campaign(name="c", status="ACTIVE", agent_id="a", rules_json={})
        self.db.add(campaign)
        self.db.flush()
        job = CallJob(
            campaign_id=campaign.id,
            customer_id=obligation.customer_id,
            obligation_id=obligation.id,
            scheduled_at=created_at,
        )
        self.db.add(job)
        self.db.flush()
        self.db.add(
            Call(
                call_job_id=job.id,
                customer_id=obligation.customer_id,
                outcome=outcome,
                created_at=created_at,
            )
        )
        self.db.commit()

    def test_exposes_contact_assistance_and_payment_history(self) -> None:
        self.seed()
        customer = list_customers(self.db)[0]

        self.assertEqual(customer.birth_year, 1984)
        self.assertEqual(customer.cohort, "CONTROL")
        self.assertEqual(customer.consent_status, "UNKNOWN")
        self.assertEqual(customer.preferred_call_window, "10:00-16:00")

        obligation = customer.obligations[0]
        # Dias restantes contra el calendario del cliente, no contra UTC.
        self.assertEqual(obligation.days_to_due, 5)
        self.assertTrue(obligation.reschedule_eligible)
        self.assertTrue(obligation.unemployment_insurance_active)
        self.assertEqual((obligation.on_time_payments, obligation.total_payments), (2, 3))

    def test_last_call_is_the_most_recent_one(self) -> None:
        obligation = self.seed()
        base = datetime.now(UTC)
        self.add_call(obligation, "NO_ANSWER", base - timedelta(hours=2))
        self.add_call(obligation, "REMINDER_DELIVERED", base - timedelta(minutes=5))

        customer = list_customers(self.db)[0]
        self.assertEqual(customer.last_call_outcome, "REMINDER_DELIVERED")

    def test_customer_without_contact_or_payments_does_not_crash(self) -> None:
        customer = Customer(
            external_ref="CUS-002",
            preferred_name="Sin contacto",
            dob_hash=hash_dob("1990-01-01"),
            birth_year=1990,
            timezone=TZ,
            language="es",
            segment="new",
            status="ACTIVE",
            cohort="TREATMENT",
        )
        self.db.add(customer)
        self.db.commit()

        result = list_customers(self.db)[0]
        self.assertIsNone(result.phone_last4)
        self.assertIsNone(result.consent_status)
        self.assertIsNone(result.last_call_at)
        self.assertFalse(result.do_not_call)


if __name__ == "__main__":
    unittest.main()
