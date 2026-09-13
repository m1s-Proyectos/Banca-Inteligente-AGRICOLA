"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("external_ref", sa.String(80), nullable=False, unique=True),
        sa.Column("preferred_name", sa.String(120), nullable=False),
        sa.Column("dob", sa.String(10), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("segment", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "customer_contacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("phone_e164", sa.String(32), nullable=False),
        sa.Column("phone_last4", sa.String(4), nullable=False),
        sa.Column("consent_status", sa.String(40), nullable=False),
        sa.Column("do_not_call", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("preferred_call_window", sa.String(80), nullable=False),
    )
    op.create_table(
        "obligations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("external_ref", sa.String(80), nullable=False, unique=True),
        sa.Column("product_type", sa.String(80), nullable=False),
        sa.Column("next_due_date", sa.Date(), nullable=False),
        sa.Column("amount_due", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
    )
    op.create_table(
        "assistance_options",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("obligation_id", sa.String(36), sa.ForeignKey("obligations.id"), nullable=False),
        sa.Column("reschedule_eligible", sa.Boolean(), nullable=False),
        sa.Column("earliest_new_date", sa.Date(), nullable=True),
        sa.Column("latest_new_date", sa.Date(), nullable=True),
        sa.Column("unemployment_insurance_active", sa.Boolean(), nullable=False),
        sa.Column("insurance_instructions", sa.Text(), nullable=False),
    )
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("agent_id", sa.String(120), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rules_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "call_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("obligation_id", sa.String(36), sa.ForeignKey("obligations.id"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_call_jobs_pending", "call_jobs", ["scheduled_at"], postgresql_where=sa.text("status = 'PENDING'"))
    op.create_table(
        "calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_job_id", sa.String(36), sa.ForeignKey("call_jobs.id"), nullable=False),
        sa.Column("retell_call_id", sa.String(120), nullable=True, unique=True),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("disconnect_reason", sa.String(120), nullable=True),
        sa.Column("right_party_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reminder_delivered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("call_successful", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sentiment", sa.String(80), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(80), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("recording_url", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "customer_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36), sa.ForeignKey("calls.id"), nullable=False),
        sa.Column("obligation_id", sa.String(36), sa.ForeignKey("obligations.id"), nullable=False),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("proposed_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("retell_call_id", sa.String(120), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("payload_redacted", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_table("customer_actions")
    op.drop_table("calls")
    op.drop_index("ix_call_jobs_pending", table_name="call_jobs")
    op.drop_table("call_jobs")
    op.drop_table("campaigns")
    op.drop_table("assistance_options")
    op.drop_table("obligations")
    op.drop_table("customer_contacts")
    op.drop_table("customers")

