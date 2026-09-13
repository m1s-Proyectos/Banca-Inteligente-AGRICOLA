import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_dob
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import AssistanceOption, Customer, Obligation
from app.services import retell


class GetAssistanceOptionsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

        self.customer = self.create_customer("CUS-ASSIST", "Maria")
        self.other_customer = self.create_customer("CUS-OTHER", "Carlos")
        self.customer_without_options = self.create_customer("CUS-NO-OPTIONS", "Ana")

        self.obligation = Obligation(
            customer_id=self.customer.id,
            external_ref="OBL-ASSIST",
            product_type="loan",
            next_due_date=datetime.now(ZoneInfo(self.customer.timezone)).date() + timedelta(days=7),
            amount_due=Decimal("125.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(self.obligation)
        self.db.flush()

        self.assistance_option = AssistanceOption(
            obligation_id=self.obligation.id,
            reschedule_eligible=True,
            earliest_new_date=date(2026, 9, 20),
            latest_new_date=date(2026, 9, 30),
            unemployment_insurance_active=False,
            insurance_instructions="",
        )
        self.db.add(self.assistance_option)

        self.no_options_obligation = Obligation(
            customer_id=self.customer_without_options.id,
            external_ref="OBL-NO-OPTIONS",
            product_type="credit_card",
            next_due_date=datetime.now(ZoneInfo(self.customer_without_options.timezone)).date() + timedelta(days=5),
            amount_due=Decimal("80.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(self.no_options_obligation)
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

    def post_assistance(self, payload: dict) -> tuple[int, dict]:
        response = self.client.post("/api/v1/retell/tools/get-assistance-options", json=payload)
        return response.status_code, response.json()

    def test_valid_token_authorizes_request(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        status_code, body = self.post_assistance(
            {"customer_ref": self.customer.id, "verification_token": token}
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(body["authorized"])

    def test_invalid_token_returns_unauthorized_response(self) -> None:
        status_code, body = self.post_assistance(
            {"customer_ref": self.customer.id, "verification_token": "invalid-token"}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"authorized": False, "options": []})

    def test_token_for_other_customer_returns_unauthorized_response(self) -> None:
        token = retell.issue_verification_token(self.db, self.other_customer.id)
        status_code, body = self.post_assistance(
            {"customer_ref": self.customer.id, "verification_token": token}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"authorized": False, "options": []})

    def test_missing_fields_return_manageable_response(self) -> None:
        status_code, body = self.post_assistance({"customer_ref": self.customer.id})

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"authorized": False, "options": []})

    def test_args_wrapper_format_works(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        status_code, body = self.post_assistance(
            {"args": {"customer_ref": self.customer.id, "verification_token": token}}
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(body["authorized"])
        self.assertEqual(len(body["options"]), 2)

    def test_valid_options_have_expected_structure(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        _, body = self.post_assistance({"customer_ref": self.customer.id, "verification_token": token})

        self.assertEqual(
            body,
            {
                "authorized": True,
                "options": [
                    {
                        "kind": "reschedule",
                        "eligible": True,
                        "earliest_new_date": "2026-09-20",
                        "latest_new_date": "2026-09-30",
                    },
                    {
                        "kind": "unemployment_insurance",
                        "eligible": False,
                        "instructions": "",
                    },
                ],
            },
        )

    def test_response_does_not_return_verification_token(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        _, body = self.post_assistance({"customer_ref": self.customer.id, "verification_token": token})

        self.assertNotIn("verification_token", body)
        for option in body["options"]:
            self.assertNotIn("verification_token", option)

    def test_valid_customer_without_options_returns_empty_options(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer_without_options.id)
        status_code, body = self.post_assistance(
            {"customer_ref": self.customer_without_options.id, "verification_token": token}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(body, {"authorized": True, "options": []})


if __name__ == "__main__":
    unittest.main()