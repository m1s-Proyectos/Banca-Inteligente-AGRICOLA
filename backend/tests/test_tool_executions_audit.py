import unittest
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_dob
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Customer, ToolExecution, VerificationToken
from app.services import retell


class ToolExecutionAuditTests(unittest.TestCase):
    """Evidencia de que la asistencia solo se consulta tras verificar identidad."""

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.customer = Customer(
            external_ref="CUS-AUDIT",
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

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def executions(self) -> list[ToolExecution]:
        return list(self.db.scalars(select(ToolExecution).order_by(ToolExecution.started_at)).all())

    def verify(self, dob: str = "1991-04-12", call_id: str | None = None) -> dict:
        payload: dict = {"customer_ref": self.customer.id, "supplied_dob": dob}
        if call_id:
            payload["call"] = {"call_id": call_id}
        return self.client.post("/api/v1/retell/tools/verify-identity", json=payload).json()

    def test_successful_verification_is_recorded(self) -> None:
        self.verify()
        records = self.executions()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].tool_name, "verify_identity")
        self.assertEqual(records[0].status, "OK")

    def test_recorded_request_never_contains_the_dob(self) -> None:
        self.verify()

        self.assertEqual(self.executions()[0].request_redacted["supplied_dob"], "[REDACTED]")

    def test_recorded_response_never_contains_the_token(self) -> None:
        self.verify()

        self.assertEqual(self.executions()[0].response_redacted["verification_token"], "[REDACTED]")

    def test_failed_verification_is_recorded_as_rejected(self) -> None:
        self.verify(dob="1980-01-01")
        records = self.executions()

        self.assertEqual(records[0].status, "REJECTED")
        self.assertEqual(records[0].error_code, "not_verified")

    def test_assistance_without_verification_is_recorded_as_rejected(self) -> None:
        self.client.post(
            "/api/v1/retell/tools/get-assistance-options",
            json={"customer_ref": self.customer.id, "verification_token": "forged"},
        )
        records = self.executions()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].tool_name, "get_assistance_options")
        self.assertEqual(records[0].status, "REJECTED")
        self.assertEqual(records[0].error_code, "not_verified")

    def test_call_id_is_persisted_on_the_record(self) -> None:
        self.verify(call_id="retell-call-123")

        self.assertEqual(self.executions()[0].retell_call_id, "retell-call-123")

    def test_token_is_bound_to_the_call_that_issued_it(self) -> None:
        token = self.verify(call_id="call-a")["verification_token"]

        self.assertTrue(retell.is_verification_token_valid(self.db, self.customer.id, token, "call-a"))
        self.assertFalse(retell.is_verification_token_valid(self.db, self.customer.id, token, "call-b"))

    def test_expired_token_is_rejected(self) -> None:
        token = self.verify()["verification_token"]
        record = self.db.scalar(select(VerificationToken).where(VerificationToken.token == token))
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        self.db.commit()

        self.assertFalse(retell.is_verification_token_valid(self.db, self.customer.id, token))

    def test_token_survives_in_the_database(self) -> None:
        """El token ya no vive en memoria del proceso."""
        token = self.verify()["verification_token"]

        self.assertIsNotNone(self.db.scalar(select(VerificationToken).where(VerificationToken.token == token)))


if __name__ == "__main__":
    unittest.main()
