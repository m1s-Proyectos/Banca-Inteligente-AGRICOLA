import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_dob
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Call, CallJob, Campaign, Customer, Obligation, WebhookEvent
from app.services import retell


class RetellWebhookEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

        self.customer = Customer(
            external_ref="CUS-WEBHOOK",
            preferred_name="Maria",
            dob_hash=hash_dob("1991-04-12"),
            birth_year=1991,
            timezone="America/El_Salvador",
            language="es",
            segment="test",
            status="ACTIVE",
        )
        self.db.add(self.customer)
        self.db.flush()

        self.campaign = Campaign(
            name="Webhook campaign",
            status="ACTIVE",
            agent_id="test-agent",
            starts_at=datetime.now(UTC),
            rules_json={},
        )
        self.db.add(self.campaign)
        self.db.flush()

        self.obligation = Obligation(
            customer_id=self.customer.id,
            external_ref="OBL-WEBHOOK",
            product_type="loan",
            next_due_date=date.today() + timedelta(days=7),
            amount_due=Decimal("125.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(self.obligation)
        self.db.flush()

        self.job = CallJob(
            campaign_id=self.campaign.id,
            customer_id=self.customer.id,
            obligation_id=self.obligation.id,
            scheduled_at=datetime.now(UTC),
            status="SENT",
        )
        self.db.add(self.job)
        self.db.flush()

        self.call = Call(
            call_job_id=self.job.id,
            retell_call_id="retell-call-123",
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

    def post_webhook(self, payload: dict, headers: dict | None = None):
        return self.client.post("/api/v1/retell/webhooks", json=payload, headers=headers or {})

    def refresh_call(self) -> Call:
        self.db.refresh(self.call)
        return self.call

    def test_call_started_updates_started_at(self) -> None:
        response = self.post_webhook({"event": "call_started", "call": {"call_id": "retell-call-123"}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertIsNotNone(self.refresh_call().started_at)

    def test_call_ended_updates_call_fields(self) -> None:
        payload = {
            "event": "call_ended",
            "call": {
                "call_id": "retell-call-123",
                "call_status": "ended",
                "disconnection_reason": "user_hangup",
                "transcript": "Cliente confirmo el recordatorio.",
                "recording_url": "https://recordings.example/call.mp3",
                "post_call_analysis_data": {
                    "call_summary": "Recordatorio entregado.",
                    "user_sentiment": "neutral",
                    "call_successful": True,
                },
            },
        }
        response = self.post_webhook(payload)

        call = self.refresh_call()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(call.status, "ENDED")
        self.assertEqual(call.disconnect_reason, "user_hangup")
        self.assertEqual(call.transcript, "Cliente confirmo el recordatorio.")
        self.assertEqual(call.recording_url, "https://recordings.example/call.mp3")
        self.assertEqual(call.summary, "Recordatorio entregado.")
        self.assertEqual(call.sentiment, "neutral")
        self.assertTrue(call.call_successful)
        self.assertEqual(call.outcome, "VERIFIED_REMINDER_DELIVERED")
        self.assertIsNotNone(call.ended_at)

    def test_call_analyzed_updates_analysis_and_ended_at(self) -> None:
        response = self.post_webhook(
            {
                "event": "call_analyzed",
                "call": {
                    "call_id": "retell-call-123",
                    "post_call_analysis_data": {
                        "call_summary": "Analisis posterior.",
                        "user_sentiment": "calm_positive",
                        "call_successful": True,
                    },
                },
            }
        )

        call = self.refresh_call()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(call.summary, "Analisis posterior.")
        self.assertEqual(call.sentiment, "calm_positive")
        self.assertTrue(call.call_successful)
        self.assertIsNotNone(call.ended_at)

    def test_partial_payload_does_not_raise_exception(self) -> None:
        response = self.post_webhook({"event": "call_ended", "call": {"call_id": "retell-call-123"}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertIsNotNone(self.refresh_call().ended_at)

    def test_unknown_event_is_recorded_without_business_logic(self) -> None:
        response = self.post_webhook({"event": "custom_event", "call": {"call_id": "retell-call-123"}})

        event = self.db.scalar(select(WebhookEvent).where(WebhookEvent.event_type == "custom_event"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(event)
        self.assertEqual(event.status, "PROCESSED")

    def test_unknown_retell_call_id_records_event_without_creating_call(self) -> None:
        response = self.post_webhook({"event": "call_ended", "call": {"call_id": "unknown-retell-call"}})

        event = self.db.scalar(select(WebhookEvent).where(WebhookEvent.retell_call_id == "unknown-retell-call"))
        missing_call = self.db.scalar(select(Call).where(Call.retell_call_id == "unknown-retell-call"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(event)
        self.assertIsNone(missing_call)

    def test_duplicate_webhook_is_not_processed_twice(self) -> None:
        payload = {"event": "call_started", "call": {"call_id": "retell-call-123"}}
        first = self.post_webhook(payload)
        second = self.post_webhook(payload)

        count = len(self.db.scalars(select(WebhookEvent).where(WebhookEvent.retell_call_id == "retell-call-123")).all())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), {"ok": True, "duplicate": True})
        self.assertEqual(count, 1)

    def test_invalid_signature_returns_unauthorized(self) -> None:
        response = self.post_webhook(
            {"event": "call_started", "call": {"call_id": "retell-call-123"}},
            headers={"X-Retell-Signature": "invalid-signature"},
        )

        self.assertEqual(response.status_code, 401)

    def test_malformed_payload_returns_manageable_response(self) -> None:
        response = self.client.post(
            "/api/v1/retell/webhooks",
            content="not-json",
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": False, "error": "invalid_payload"})

    def test_non_object_payload_returns_manageable_response(self) -> None:
        response = self.client.post("/api/v1/retell/webhooks", json=["not", "object"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": False, "error": "invalid_payload"})


if __name__ == "__main__":
    unittest.main()