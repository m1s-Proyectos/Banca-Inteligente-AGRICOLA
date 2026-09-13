import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_dob
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AssistanceOption,
    Call,
    CallJob,
    Campaign,
    Customer,
    CustomerAction,
    Obligation,
)
from app.services import retell


class RequestRescheduleEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

        self.customer = self.create_customer("CUS-RSCH", "Maria")
        self.other_customer = self.create_customer("CUS-RSCH-OTHER", "Carlos")
        self.customer_without_call = self.create_customer("CUS-RSCH-NO-CALL", "Ana")
        self.customer_not_eligible = self.create_customer("CUS-RSCH-NOT-ELIGIBLE", "Lucia")
        self.campaign = Campaign(
            name="Test campaign",
            status="ACTIVE",
            agent_id="test-agent",
            starts_at=datetime.now(UTC),
            rules_json={},
        )
        self.db.add(self.campaign)
        self.db.flush()

        self.obligation = self.create_obligation(self.customer.id, "OBL-RSCH")
        # Rango aprobado del guion: toda fecha propuesta debe caer dentro.
        self.db.add(
            AssistanceOption(
                obligation_id=self.obligation.id,
                reschedule_eligible=True,
                earliest_new_date=date(2026, 9, 18),
                latest_new_date=date(2026, 9, 25),
                unemployment_insurance_active=False,
                insurance_instructions="",
            )
        )

        self.no_call_obligation = self.create_obligation(self.customer_without_call.id, "OBL-RSCH-NO-CALL")

        self.not_eligible_obligation = self.create_obligation(self.customer_not_eligible.id, "OBL-RSCH-NOT-ELIGIBLE")
        self.db.add(
            AssistanceOption(
                obligation_id=self.not_eligible_obligation.id,
                reschedule_eligible=False,
                earliest_new_date=date(2026, 9, 18),
                latest_new_date=date(2026, 9, 25),
                unemployment_insurance_active=False,
                insurance_instructions="",
            )
        )

        self.call_job = self.create_call_job(self.customer.id, self.obligation.id)
        self.call = self.create_call(self.call_job.id, self.customer.id)
        # El cliente sin elegibilidad sí tiene llamada: lo que lo bloquea es la opción.
        not_eligible_call_job = self.create_call_job(self.customer_not_eligible.id, self.not_eligible_obligation.id)
        self.create_call(not_eligible_call_job.id, self.customer_not_eligible.id)
        self.db.commit()

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def create_customer(self, external_ref: str, name: str) -> Customer:
        customer = Customer(
            external_ref=external_ref,
            preferred_name=name,
            dob_hash=hash_dob("1991-04-12"),
            birth_year=1991,
            timezone="America/El_Salvador",
            language="es",
            segment="test",
            status="ACTIVE",
        )
        self.db.add(customer)
        self.db.flush()
        return customer

    def create_obligation(self, customer_id: str, external_ref: str) -> Obligation:
        customer = self.db.get(Customer, customer_id)
        assert customer is not None
        obligation = Obligation(
            customer_id=customer_id,
            external_ref=external_ref,
            product_type="loan",
            next_due_date=datetime.now(ZoneInfo(customer.timezone)).date() + timedelta(days=7),
            amount_due=Decimal("125.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(obligation)
        self.db.flush()
        return obligation

    def create_call_job(self, customer_id: str, obligation_id: str) -> CallJob:
        call_job = CallJob(
            campaign_id=self.campaign.id,
            customer_id=customer_id,
            obligation_id=obligation_id,
            scheduled_at=datetime.now(UTC),
            status="SENT",
        )
        self.db.add(call_job)
        self.db.flush()
        return call_job

    def create_call(self, call_job_id: str, customer_id: str) -> Call:
        call = Call(
            call_job_id=call_job_id,
            customer_id=customer_id,
            status="REGISTERED",
            outcome="PENDING",
        )
        self.db.add(call)
        self.db.flush()
        return call

    def post_reschedule(self, payload: dict) -> tuple[int, dict]:
        response = self.client.post("/api/v1/retell/tools/request-reschedule", json=payload)
        return response.status_code, response.json()

    def test_valid_token_accepts_request_within_range(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": True, "status": "PENDING_REVIEW"})

    def test_invalid_token_rejects_request(self) -> None:
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": "invalid-token", "proposed_date": "2026-09-20"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "not_verified"})

    def test_token_for_other_customer_rejects_request(self) -> None:
        token = retell.issue_verification_token(self.db, self.other_customer.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "not_verified"})

    def test_missing_customer_ref_returns_manageable_response(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        status_code, body = self.post_reschedule(
            {"verification_token": token, "proposed_date": "2026-09-20"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "invalid_request"})

    def test_missing_verification_token_returns_manageable_response(self) -> None:
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "proposed_date": "2026-09-20"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "invalid_request"})

    def test_missing_proposed_date_returns_manageable_response(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "invalid_request"})

    def test_args_wrapper_format_works(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        status_code, body = self.post_reschedule(
            {"args": {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-09-20"}}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": True, "status": "PENDING_REVIEW"})

    def test_obligation_ref_is_honored(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        status_code, body = self.post_reschedule(
            {
                "customer_ref": self.customer.id,
                "verification_token": token,
                "proposed_date": "2026-09-20",
                "obligation_ref": self.obligation.id,
            }
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": True, "status": "PENDING_REVIEW"})

    def test_valid_proposal_creates_customer_action(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )

        action = self.db.scalar(select(CustomerAction).where(CustomerAction.call_id == self.call.id))
        assert action is not None
        self.assertEqual(action.obligation_id, self.obligation.id)
        self.assertEqual(action.type, "RESCHEDULE_REQUEST")
        self.assertEqual(action.status, "PENDING_REVIEW")
        self.assertEqual(action.proposed_date, date(2026, 9, 20))

    def test_date_outside_approved_range_is_rejected_with_bounds(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-10-15"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(
            body,
            {
                "accepted": False,
                "reason": "out_of_range",
                "earliest_new_date": "2026-09-18",
                "latest_new_date": "2026-09-25",
            },
        )

        actions = self.db.scalars(select(CustomerAction)).all()
        self.assertEqual(actions, [])

    def test_customer_without_eligibility_is_rejected(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer_not_eligible.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer_not_eligible.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "not_eligible"})

    def test_missing_call_returns_safe_response_without_exception(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer_without_call.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer_without_call.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "missing_context"})

    def test_response_never_returns_verification_token(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        _, success_body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )
        _, failure_body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": "invalid-token", "proposed_date": "2026-09-20"}
        )

        self.assertNotIn("verification_token", success_body)
        self.assertNotIn("verification_token", failure_body)

    def test_invalid_proposed_date_returns_manageable_response(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "not-a-date"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "invalid_request"})


if __name__ == "__main__":
    unittest.main()
