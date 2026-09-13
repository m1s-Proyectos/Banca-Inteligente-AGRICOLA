import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Call, CallJob, Campaign, Customer, CustomerAction, Obligation
from app.services import retell


class RequestRescheduleEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        retell._verification_tokens.clear()
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
        self.no_call_obligation = self.create_obligation(self.customer_without_call.id, "OBL-RSCH-NO-CALL")
        self.call_job = CallJob(
            campaign_id=self.campaign.id,
            customer_id=self.customer.id,
            obligation_id=self.obligation.id,
            scheduled_at=datetime.now(UTC),
            status="SENT",
        )
        self.db.add(self.call_job)
        self.db.flush()
        self.call = Call(
            call_job_id=self.call_job.id,
            customer_id=self.customer.id,
            status="REGISTERED",
            outcome="PENDING",
        )
        self.db.add(self.call)
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
        retell._verification_tokens.clear()

    def create_customer(self, external_ref: str, name: str) -> Customer:
        customer = Customer(
            external_ref=external_ref,
            preferred_name=name,
            dob="1991-04-12",
            timezone="America/El_Salvador",
            language="es",
            segment="test",
            status="ACTIVE",
        )
        self.db.add(customer)
        self.db.flush()
        return customer

    def create_obligation(self, customer_id: str, external_ref: str) -> Obligation:
        obligation = Obligation(
            customer_id=customer_id,
            external_ref=external_ref,
            product_type="loan",
            next_due_date=date.today() + timedelta(days=7),
            amount_due=Decimal("125.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(obligation)
        self.db.flush()
        return obligation

    def post_reschedule(self, payload: dict) -> tuple[int, dict]:
        response = self.client.post("/api/v1/retell/tools/request-reschedule", json=payload)
        return response.status_code, response.json()

    def test_valid_token_accepts_request(self) -> None:
        token = retell.issue_verification_token(self.customer.id)
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
        token = retell.issue_verification_token(self.other_customer.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "not_verified"})

    def test_missing_customer_ref_returns_manageable_response(self) -> None:
        token = retell.issue_verification_token(self.customer.id)
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
        token = retell.issue_verification_token(self.customer.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "invalid_request"})

    def test_args_wrapper_format_works(self) -> None:
        token = retell.issue_verification_token(self.customer.id)
        status_code, body = self.post_reschedule(
            {"args": {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-09-20"}}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": True, "status": "PENDING_REVIEW"})

    def test_valid_proposal_creates_customer_action(self) -> None:
        token = retell.issue_verification_token(self.customer.id)
        self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )

        action = self.db.scalar(select(CustomerAction).where(CustomerAction.call_id == self.call.id))
        self.assertIsNotNone(action)
        self.assertEqual(action.obligation_id, self.obligation.id)
        self.assertEqual(action.type, "RESCHEDULE_REQUEST")
        self.assertEqual(action.status, "PENDING_REVIEW")
        self.assertEqual(action.proposed_date, date(2026, 9, 20))

    def test_missing_call_returns_safe_response_without_exception(self) -> None:
        token = retell.issue_verification_token(self.customer_without_call.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer_without_call.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "missing_context"})

    def test_response_never_returns_verification_token(self) -> None:
        token = retell.issue_verification_token(self.customer.id)
        _, success_body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "2026-09-20"}
        )
        _, failure_body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": "invalid-token", "proposed_date": "2026-09-20"}
        )

        self.assertNotIn("verification_token", success_body)
        self.assertNotIn("verification_token", failure_body)

    def test_invalid_proposed_date_returns_manageable_response(self) -> None:
        token = retell.issue_verification_token(self.customer.id)
        status_code, body = self.post_reschedule(
            {"customer_ref": self.customer.id, "verification_token": token, "proposed_date": "not-a-date"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"accepted": False, "reason": "invalid_request"})


if __name__ == "__main__":
    unittest.main()