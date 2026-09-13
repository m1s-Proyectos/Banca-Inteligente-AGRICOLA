import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_dob
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Customer, VerificationToken


class VerifyIdentityEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.customer = Customer(
            external_ref="CUS-HTTP",
            preferred_name="Maria",
            dob_hash=hash_dob("1991-04-12"),
            birth_year=1991,
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

    def post_verify(self, payload: dict) -> tuple[int, dict]:
        response = self.client.post("/api/v1/retell/tools/verify-identity", json=payload)
        return response.status_code, response.json()

    def test_valid_identity(self) -> None:
        status_code, body = self.post_verify(
            {"customer_ref": self.customer.id, "supplied_dob": "1991-04-12"}
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(body["verified"])
        self.assertEqual(body["message"], "Identidad verificada")

    def test_invalid_identity_returns_safe_failure(self) -> None:
        status_code, body = self.post_verify(
            {"customer_ref": self.customer.id, "supplied_dob": "1990-01-01"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"verified": False, "verification_token": None, "message": ""})

    def test_unknown_customer_returns_safe_failure(self) -> None:
        status_code, body = self.post_verify(
            {"customer_ref": "missing-customer", "supplied_dob": "1991-04-12"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"verified": False, "verification_token": None, "message": ""})

    def test_args_wrapper_format(self) -> None:
        status_code, body = self.post_verify(
            {"args": {"customer_ref": self.customer.id, "supplied_dob": "1991-04-12"}}
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(body["verified"])
        self.assertIsInstance(body["verification_token"], str)

    def test_missing_required_fields_returns_safe_failure(self) -> None:
        status_code, body = self.post_verify({"customer_ref": self.customer.id})

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"verified": False, "verification_token": None, "message": ""})

    def test_successful_response_contains_verification_token(self) -> None:
        _, body = self.post_verify({"customer_ref": self.customer.id, "supplied_dob": "1991-04-12"})

        self.assertTrue(body["verification_token"])
        self.assertGreaterEqual(len(body["verification_token"]), 40)

    def test_failed_response_does_not_contain_valid_token(self) -> None:
        _, body = self.post_verify({"customer_ref": self.customer.id, "supplied_dob": "1990-01-01"})

        self.assertIsNone(body["verification_token"])
        self.assertEqual(self.db.scalar(select(func.count(VerificationToken.id))), 0)


if __name__ == "__main__":
    unittest.main()