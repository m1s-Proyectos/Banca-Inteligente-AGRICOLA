"""hash dob, auditoria de herramientas y resultados de pago

Revision ID: 0002_pii_audit_payments
Revises: 0001_initial
Create Date: 2026-09-13
"""

from datetime import date

import sqlalchemy as sa
from alembic import op

from app.core.security import hash_dob, normalize_dob

revision = "0002_pii_audit_payments"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def backfill_customers() -> None:
    """Deriva dob_hash y birth_year de la fecha en claro antes de borrarla.

    Se usa hash_dob del codigo de la aplicacion a proposito: si la migracion
    calculara el HMAC por su cuenta (por ejemplo leyendo APP_SECRET solo de
    os.environ) podria diferir de lo que calcula la app en runtime —
    pydantic-settings tambien lee el archivo .env — y la verificacion de
    identidad fallaria en silencio para todas las filas existentes.
    """
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, dob FROM customers")).fetchall()
    for row in rows:
        # Falla ruidosamente si algun dob no es parseable: mejor eso que
        # almacenar un birth_year basura en una columna no nullable.
        birth_year = date.fromisoformat(normalize_dob(row.dob)).year
        connection.execute(
            sa.text("UPDATE customers SET dob_hash = :dob_hash, birth_year = :birth_year WHERE id = :id"),
            {"dob_hash": hash_dob(row.dob), "birth_year": birth_year, "id": row.id},
        )


def upgrade() -> None:
    # batch_alter_table para que la migracion corra igual en PostgreSQL y SQLite.
    with op.batch_alter_table("customers") as batch_op:
        batch_op.add_column(sa.Column("dob_hash", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("birth_year", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("cohort", sa.String(20), nullable=False, server_default="TREATMENT")
        )

    backfill_customers()

    with op.batch_alter_table("customers") as batch_op:
        batch_op.alter_column("dob_hash", existing_type=sa.String(64), nullable=False)
        batch_op.alter_column("birth_year", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("dob")

    op.create_table(
        "verification_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("call_id", sa.String(36), sa.ForeignKey("calls.id"), nullable=True),
        sa.Column("retell_call_id", sa.String(120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "tool_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36), sa.ForeignKey("calls.id"), nullable=True),
        sa.Column("retell_call_id", sa.String(120), nullable=True),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("request_redacted", sa.JSON(), nullable=False),
        sa.Column("response_redacted", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
    )
    op.create_index("ix_tool_executions_call_id", "tool_executions", ["call_id", "started_at"])

    op.create_table(
        "payment_outcomes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("obligation_id", sa.String(36), sa.ForeignKey("obligations.id"), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("paid_at", sa.Date(), nullable=True),
        sa.Column("amount_paid", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_batch_id", sa.String(80), nullable=True),
    )
    op.create_index("ix_payment_outcomes_obligation_id", "payment_outcomes", ["obligation_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_outcomes_obligation_id", table_name="payment_outcomes")
    op.drop_table("payment_outcomes")
    op.drop_index("ix_tool_executions_call_id", table_name="tool_executions")
    op.drop_table("tool_executions")
    op.drop_table("verification_tokens")

    # El dob en claro no se puede reconstruir desde el HMAC: se repuebla vacio y
    # hay que volver a sembrar. Es el precio de que el hash sea irreversible.
    with op.batch_alter_table("customers") as batch_op:
        batch_op.add_column(sa.Column("dob", sa.String(10), nullable=False, server_default=""))
        batch_op.drop_column("cohort")
        batch_op.drop_column("birth_year")
        batch_op.drop_column("dob_hash")
