import unittest
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.security import hash_dob
from app.db.base import Base
from app.models import Customer, Obligation, PaymentOutcome
from app.services.dashboard import on_time_payment_rate


class PaymentMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def add_customer(self, ref: str, cohort: str) -> Customer:
        customer = Customer(
            external_ref=ref,
            preferred_name=ref,
            dob_hash=hash_dob("1990-01-01"),
            birth_year=1990,
            timezone="America/El_Salvador",
            language="es",
            segment="test",
            status="ACTIVE",
            cohort=cohort,
        )
        self.db.add(customer)
        self.db.flush()
        return customer

    def add_outcomes(self, customer: Customer, statuses: list[str]) -> None:
        obligation = Obligation(
            customer_id=customer.id,
            external_ref=f"OBL-{customer.external_ref}",
            product_type="loan",
            next_due_date=date.today() + timedelta(days=7),
            amount_due=Decimal("100.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(obligation)
        self.db.flush()
        for index, status in enumerate(statuses):
            self.db.add(
                PaymentOutcome(
                    obligation_id=obligation.id,
                    due_date=date.today() - timedelta(days=30 * (index + 1)),
                    status=status,
                    source_batch_id="test",
                )
            )
        self.db.commit()

    def test_rate_counts_only_its_own_cohort(self) -> None:
        self.add_outcomes(self.add_customer("T1", "TREATMENT"), ["ON_TIME", "ON_TIME", "ON_TIME", "LATE"])
        self.add_outcomes(self.add_customer("C1", "CONTROL"), ["ON_TIME", "LATE"])

        self.assertEqual(on_time_payment_rate(self.db, "TREATMENT"), 0.75)
        self.assertEqual(on_time_payment_rate(self.db, "CONTROL"), 0.5)

    def test_no_data_returns_none_not_zero(self) -> None:
        """Sin medicion no es lo mismo que nadie pago."""
        self.assertIsNone(on_time_payment_rate(self.db, "TREATMENT"))

    def test_all_late_is_zero_not_none(self) -> None:
        self.add_outcomes(self.add_customer("T2", "TREATMENT"), ["LATE", "LATE"])

        self.assertEqual(on_time_payment_rate(self.db, "TREATMENT"), 0.0)


if __name__ == "__main__":
    unittest.main()
