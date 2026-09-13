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
        self.insurance_customer = self.create_customer("CUS-INSURANCE", "Jose")

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

        # Segunda obligación del mismo cliente, sin opciones configuradas: sirve
        # para comprobar que obligation_ref selecciona la obligación correcta.
        self.second_obligation = self.create_obligation(self.customer, "OBL-ASSIST-2", days_ahead=15)

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

        # Cliente cuyo único beneficio activo es el seguro de desempleo.
        self.insurance_obligation = self.create_obligation(self.insurance_customer, "OBL-INSURANCE", days_ahead=9)
        self.db.add(
            AssistanceOption(
                obligation_id=self.insurance_obligation.id,
                reschedule_eligible=False,
                unemployment_insurance_active=True,
                insurance_instructions="Escalar a asesor humano para validar cobertura de desempleo.",
            )
        )
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

    def create_obligation(self, customer: Customer, external_ref: str, days_ahead: int) -> Obligation:
        obligation = Obligation(
            customer_id=customer.id,
            external_ref=external_ref,
            product_type="loan",
            # Día calendario del cliente, no el reloj del servidor.
            next_due_date=datetime.now(ZoneInfo(customer.timezone)).date() + timedelta(days=days_ahead),
            amount_due=Decimal("125.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(obligation)
        self.db.flush()
        return obligation

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
        # Solo opciones activas: la de seguro inactivo no debe aparecer.
        self.assertEqual(len(body["options"]), 1)

    def test_only_active_options_are_listed_with_approved_text(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        _, body = self.post_assistance({"customer_ref": self.customer.id, "verification_token": token})

        self.assertEqual(len(body["options"]), 1)
        option = body["options"][0]
        self.assertEqual(option["kind"], "reschedule")
        self.assertIn("20 de septiembre de 2026", option["text"])
        self.assertIn("30 de septiembre de 2026", option["text"])

    def test_insurance_only_customer_gets_insurance_option_with_instructions(self) -> None:
        token = retell.issue_verification_token(self.db, self.insurance_customer.id)
        _, body = self.post_assistance(
            {"customer_ref": self.insurance_customer.id, "verification_token": token}
        )

        self.assertEqual(
            body["options"],
            [
                {
                    "kind": "unemployment_insurance",
                    "text": "Escalar a asesor humano para validar cobertura de desempleo.",
                }
            ],
        )

    def test_obligation_ref_selects_specific_obligation(self) -> None:
        token = retell.issue_verification_token(self.db, self.customer.id)
        _, body = self.post_assistance(
            {
                "customer_ref": self.customer.id,
                "verification_token": token,
                "obligation_ref": self.second_obligation.id,
            }
        )

        # La segunda obligación no tiene opciones configuradas.
        self.assertEqual(body, {"authorized": True, "options": []})

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
