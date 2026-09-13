import unittest
from unittest.mock import patch

from app.db.base import Base
from app.models import Customer
from app.services import retell
from app.services.retell import verify_identity
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class VerificationTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.customer = Customer(
            external_ref="CUS-TEST",
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

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def issue_token(self, customer_id: str | None = None) -> str:
        return retell.issue_verification_token(customer_id or self.customer.id)

    def test_valid_identity_returns_verification_token(self) -> None:
        result = verify_identity(self.db, self.customer.id, "1991-04-12")

        self.assertTrue(result["verified"])
        self.assertIsInstance(result["verification_token"], str)
        self.assertTrue(result["verification_token"])

    def test_two_valid_verifications_produce_different_tokens(self) -> None:
        first = verify_identity(self.db, self.customer.id, "1991-04-12")
        second = verify_identity(self.db, self.customer.id, "1991-04-12")

        self.assertNotEqual(first["verification_token"], second["verification_token"])

    def test_verification_token_does_not_contain_customer_id(self) -> None:
        result = verify_identity(self.db, self.customer.id, "1991-04-12")

        self.assertNotIn(self.customer.id, result["verification_token"])

    def test_verification_token_has_reasonable_length(self) -> None:
        result = verify_identity(self.db, self.customer.id, "1991-04-12")

        self.assertGreaterEqual(len(result["verification_token"]), 40)

    def test_invalid_identity_returns_no_token(self) -> None:
        result = verify_identity(self.db, self.customer.id, "1990-01-01")

        self.assertFalse(result["verified"])
        self.assertIsNone(result["verification_token"])

    def test_issued_token_validates_for_same_customer(self) -> None:
        token = self.issue_token()

        self.assertTrue(retell.is_verification_token_valid(self.customer.id, token))

    def test_issued_token_rejects_other_customer(self) -> None:
        token = self.issue_token()

        self.assertFalse(retell.is_verification_token_valid("other-customer", token))

    def test_expired_token_is_rejected(self) -> None:
        with patch.object(retell, "VERIFICATION_TOKEN_TTL_SECONDS", -60):
            token = self.issue_token()

        self.assertFalse(retell.is_verification_token_valid(self.customer.id, token))

    def test_tampered_token_is_rejected(self) -> None:
        token = self.issue_token()
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")

        self.assertFalse(retell.is_verification_token_valid(self.customer.id, tampered))

    def test_malformed_token_is_rejected(self) -> None:
        for candidate in ("", "abc", "123.abc", "123.abc.def.ghi", None):
            self.assertFalse(retell.is_verification_token_valid(self.customer.id, candidate))


if __name__ == "__main__":
    unittest.main()
