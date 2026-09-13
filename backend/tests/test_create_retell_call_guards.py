import asyncio
import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_dob
from app.db.base import Base
from app.models import CallJob, Campaign, Customer, Obligation
from app.services.retell import build_dynamic_variables, create_retell_call


class CreateRetellCallGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

        self.campaign = Campaign(
            name="Test campaign",
            status="ACTIVE",
            agent_id="test-agent",
            starts_at=datetime.now(UTC),
            rules_json={},
        )
        self.db.add(self.campaign)
        self.customer = Customer(
            external_ref="CUS-GUARD",
            preferred_name="Maria",
            dob_hash=hash_dob("1990-01-01"),
            birth_year=1990,
            timezone="America/El_Salvador",
            language="es",
            segment="test",
            status="ACTIVE",
        )
        self.db.add(self.customer)
        self.db.flush()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def today_for_customer(self) -> date:
        # El guard de vencido compara contra el día calendario del cliente
        # (America/El_Salvador), no contra UTC ni el reloj del servidor.
        return datetime.now(ZoneInfo(self.customer.timezone)).date()

    def create_obligation(self, due_date: date) -> Obligation:
        obligation = Obligation(
            customer_id=self.customer.id,
            external_ref=f"OBL-{due_date.isoformat()}",
            product_type="loan",
            next_due_date=due_date,
            amount_due=Decimal("125.00"),
            currency="USD",
            status="CURRENT",
        )
        self.db.add(obligation)
        self.db.flush()
        return obligation

    def create_job(self, obligation_id: str) -> CallJob:
        job = CallJob(
            campaign_id=self.campaign.id,
            customer_id=self.customer.id,
            obligation_id=obligation_id,
            scheduled_at=datetime.now(UTC),
            status="CLAIMED",
        )
        self.db.add(job)
        self.db.flush()
        return job

    def test_overdue_obligation_blocks_call(self) -> None:
        obligation = self.create_obligation(self.today_for_customer() - timedelta(days=1))
        job = self.create_job(obligation.id)

        call = asyncio.run(create_retell_call(self.db, job))

        self.assertEqual(call.status, "BLOCKED")
        self.assertEqual(call.outcome, "BLOCKED_OVERDUE")
        self.assertEqual(job.status, "BLOCKED")
        assert job.last_error is not None
        self.assertIn("vencida", job.last_error)

    def test_due_today_is_not_blocked_by_overdue_guard(self) -> None:
        # Vence hoy (dias_restantes = 0): el guardrail del guion permite el flujo.
        # Sin contacto primario se bloquea luego por consentimiento, no por vencido.
        obligation = self.create_obligation(self.today_for_customer())
        job = self.create_job(obligation.id)

        call = asyncio.run(create_retell_call(self.db, job))

        self.assertEqual(call.outcome, "BLOCKED_BY_CONSENT")

    def test_future_obligation_reaches_consent_check(self) -> None:
        obligation = self.create_obligation(self.today_for_customer() + timedelta(days=7))
        job = self.create_job(obligation.id)

        call = asyncio.run(create_retell_call(self.db, job))

        self.assertEqual(call.status, "BLOCKED")
        self.assertEqual(call.outcome, "BLOCKED_BY_CONSENT")
        self.assertEqual(job.status, "BLOCKED")

    def test_missing_obligation_blocks_with_context_error(self) -> None:
        job = self.create_job("obligation-that-does-not-exist")

        call = asyncio.run(create_retell_call(self.db, job))

        self.assertEqual(call.status, "BLOCKED")
        self.assertEqual(call.outcome, "BLOCKED_MISSING_CONTEXT")

    def test_dynamic_variables_follow_script_contract(self) -> None:
        # Un solo "hoy" para todo el test: si medianoche local cae entre líneas,
        # days_remaining sigue siendo 7.
        today = self.today_for_customer()
        obligation = self.create_obligation(today + timedelta(days=7))
        days_remaining = (obligation.next_due_date - today).days

        variables = build_dynamic_variables(self.customer, obligation, days_remaining)

        self.assertEqual(variables["customer_ref"], self.customer.id)
        self.assertEqual(variables["obligation_ref"], obligation.id)
        self.assertEqual(variables["nom_cliente"], "Maria")
        self.assertEqual(variables["fecha_pago"], obligation.next_due_date.isoformat())
        self.assertEqual(variables["monto_deuda"], "125.00")
        self.assertEqual(variables["moneda"], "USD")
        self.assertEqual(variables["dias_restantes_pago"], "7")
        self.assertEqual(variables["nom_producto"], "loan")
        # birth_year 1990: la edad es determinista sin importar el día del test.
        self.assertEqual(variables["edad_cliente"], str(today.year - 1990))
        self.assertEqual(variables["language"], "es")
        self.assertEqual(variables["timezone"], "America/El_Salvador")
        # Compatibilidad con el contrato original.
        self.assertEqual(variables["preferred_name"], "Maria")
        self.assertEqual(variables["next_due_date"], obligation.next_due_date.isoformat())
        self.assertTrue(all(isinstance(value, str) for value in variables.values()))


if __name__ == "__main__":
    unittest.main()
