import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.security import hash_dob
from app.db.base import Base
from app.models import Customer
from app.services.retell import verify_identity


class DobHashingTests(unittest.TestCase):
    """La fecha de nacimiento es el secreto de autenticacion del sistema."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.customer = Customer(
            external_ref="CUS-HASH",
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

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_stored_column_does_not_contain_the_date(self) -> None:
        self.assertNotIn("1991", self.customer.dob_hash)
        self.assertNotIn("04-12", self.customer.dob_hash)
        self.assertEqual(len(self.customer.dob_hash), 64)

    def test_customer_model_has_no_plaintext_dob_column(self) -> None:
        self.assertNotIn("dob", Customer.__table__.c.keys())

    def test_correct_date_still_verifies(self) -> None:
        self.assertTrue(verify_identity(self.db, self.customer.id, "1991-04-12")["verified"])

    def test_wrong_date_does_not_verify(self) -> None:
        self.assertFalse(verify_identity(self.db, self.customer.id, "1991-04-13")["verified"])

    def test_slash_format_is_normalized_before_hashing(self) -> None:
        self.assertTrue(verify_identity(self.db, self.customer.id, "1991/04/12")["verified"])

    def test_birth_year_is_enough_to_derive_age(self) -> None:
        self.assertEqual(self.customer.birth_year, 1991)


if __name__ == "__main__":
    unittest.main()
