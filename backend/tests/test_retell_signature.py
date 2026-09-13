import hashlib
import hmac
import json
import time
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Customer
from app.services import retell


RETELL_TEST_SECRET = "retell-test-secret"


def encode_body(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def retell_signature(raw_body: bytes, timestamp: int | None = None, secret: str = RETELL_TEST_SECRET) -> str:
    timestamp_value = str(timestamp or int(time.time()))
    digest = hmac.new(
        secret.encode("utf-8"),
        raw_body + timestamp_value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"v={timestamp_value},d={digest}"


class RetellSignatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_fake_data_only = retell.settings.fake_data_only
        self.original_retell_api_key = retell.settings.retell_api_key
        retell.settings.fake_data_only = False
        retell.settings.retell_api_key = RETELL_TEST_SECRET
        retell._verification_tokens.clear()

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.customer = Customer(
            external_ref="CUS-SIGNATURE",
            preferred_name="Maria",
            dob="1991-04-12",
            timezone="America/El_Salvador",
            language="es",
            segment="test",
            status="ACTIVE",
        )
        self.db.add(self.customer)
        self.db.commit()
        self.db.refresh(self.customer)

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
        retell.settings.fake_data_only = self.original_fake_data_only
        retell.settings.retell_api_key = self.original_retell_api_key

    def signed_post(self, url: str, payload: dict, signature: str | None = None):
        raw_body = encode_body(payload)
        headers = {"Content-Type": "application/json"}
        if signature is not None:
            headers["X-Retell-Signature"] = signature
        return self.client.post(url, content=raw_body, headers=headers)

    def test_valid_signature_is_accepted(self) -> None:
        raw_body = encode_body({"event": "call_started"})

        self.assertTrue(retell.verify_retell_signature(raw_body, retell_signature(raw_body)))

    def test_invalid_signature_is_rejected(self) -> None:
        raw_body = encode_body({"event": "call_started"})

        self.assertFalse(retell.verify_retell_signature(raw_body, "v=123,d=invalid"))

    def test_expired_timestamp_is_rejected(self) -> None:
        raw_body = encode_body({"event": "call_started"})
        expired_timestamp = int(time.time()) - retell.RETELL_SIGNATURE_TOLERANCE_SECONDS - 1

        self.assertFalse(retell.verify_retell_signature(raw_body, retell_signature(raw_body, expired_timestamp)))

    def test_signature_calculated_over_different_body_is_rejected(self) -> None:
        raw_body = encode_body({"event": "call_started"})
        other_body = encode_body({"event": "call_ended"})

        self.assertFalse(retell.verify_retell_signature(raw_body, retell_signature(other_body)))

    def test_missing_header_is_rejected_when_validation_is_active(self) -> None:
        raw_body = encode_body({"event": "call_started"})

        self.assertFalse(retell.verify_retell_signature(raw_body, None))

    def test_invalid_header_format_is_rejected(self) -> None:
        raw_body = encode_body({"event": "call_started"})

        self.assertFalse(retell.verify_retell_signature(raw_body, "invalid-format"))

    def test_webhook_accepts_valid_retell_signature(self) -> None:
        payload = {"event": "call_started", "call": {"call_id": "unknown-retell-call"}}
        raw_body = encode_body(payload)
        response = self.signed_post("/api/v1/retell/webhooks", payload, retell_signature(raw_body))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_custom_function_accepts_valid_retell_signature(self) -> None:
        payload = {"customer_ref": self.customer.id, "supplied_dob": "1991-04-12"}
        raw_body = encode_body(payload)
        response = self.signed_post(
            "/api/v1/retell/tools/verify-identity",
            payload,
            retell_signature(raw_body),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["verified"])

    def test_custom_function_rejects_invalid_retell_signature_when_validation_is_active(self) -> None:
        payload = {"customer_ref": self.customer.id, "supplied_dob": "1991-04-12"}
        response = self.signed_post(
            "/api/v1/retell/tools/verify-identity",
            payload,
            "v=123,d=invalid",
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
