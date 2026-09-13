import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import retell as retell_routes
from app.core.security import hash_dob
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Call, CallJob, Customer, CustomerContact, Obligation
from app.services import retell


class FakeAsyncClient:
    request_json: dict | None = None

    def __init__(self, timeout: int) -> None:
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, url: str, *, json: dict, headers: dict) -> httpx.Response:
        self.__class__.request_json = json
        request = httpx.Request("POST", url, headers=headers)
        return httpx.Response(
            201,
            request=request,
            json={
                "call_id": "call_web_demo",
                "access_token": "ephemeral-browser-token",
                "transport": "livekit",
            },
        )


class RetellWebCallEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        customer = Customer(
            external_ref="CUS-WEB",
            preferred_name="María",
            dob_hash=hash_dob("1991-04-12"),
            birth_year=1991,
            timezone="America/El_Salvador",
            language="es",
            segment="test",
            status="ACTIVE",
        )
        self.db.add(customer)
        self.db.flush()
        self.db.add(
            CustomerContact(
                customer_id=customer.id,
                phone_e164="+50370000001",
                phone_last4="0001",
                consent_status="OPTED_IN",
                do_not_call=False,
                is_primary=True,
            )
        )
        obligation = Obligation(
            customer_id=customer.id,
            external_ref="OBL-WEB",
            product_type="loan",
            next_due_date=datetime.now(UTC).date() + timedelta(days=7),
            amount_due=Decimal("98.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(obligation)
        self.db.commit()
        self.customer_id = customer.id
        self.obligation_id = obligation.id

        self.original_settings = (
            retell.settings.fake_data_only,
            retell.settings.retell_api_key,
            retell.settings.retell_agent_id,
            retell.settings.retell_agent_version,
        )
        retell.settings.fake_data_only = True
        retell.settings.retell_api_key = "retell-test-key"
        retell.settings.retell_agent_id = "agent_demo"
        retell.settings.retell_agent_version = 1
        retell_routes._last_web_call_at = 0

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        (
            retell.settings.fake_data_only,
            retell.settings.retell_api_key,
            retell.settings.retell_agent_id,
            retell.settings.retell_agent_version,
        ) = self.original_settings
        retell_routes._last_web_call_at = 0

    @patch("app.services.retell.httpx.AsyncClient", FakeAsyncClient)
    def test_creates_web_call_and_never_persists_access_token(self) -> None:
        response = self.client.post(
            "/api/v1/retell/web-calls",
            json={"customer_id": self.customer_id, "obligation_id": self.obligation_id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"call_id": "call_web_demo", "access_token": "ephemeral-browser-token"},
        )
        job = self.db.scalar(select(CallJob))
        call = self.db.scalar(select(Call))
        assert job is not None and call is not None
        self.assertEqual(job.status, "SENT")
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(call.retell_call_id, "call_web_demo")
        self.assertNotIn("access_token", call.raw_payload or {})
        self.assertEqual(FakeAsyncClient.request_json["agent_version"], 1)
        self.assertEqual(
            FakeAsyncClient.request_json["retell_llm_dynamic_variables"]["customer_ref"],
            self.customer_id,
        )

    @patch("app.services.retell.httpx.AsyncClient", FakeAsyncClient)
    def test_rate_limits_repeated_public_demo_calls(self) -> None:
        payload = {"customer_id": self.customer_id, "obligation_id": self.obligation_id}

        first = self.client.post("/api/v1/retell/web-calls", json=payload)
        second = self.client.post("/api/v1/retell/web-calls", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


if __name__ == "__main__":
    unittest.main()
