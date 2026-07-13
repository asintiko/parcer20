"""Add automation auxiliary tables for reconciliation/duplicates/config.

Revision ID: 20260220_0011
Revises: 20260220_0010
Create Date: 2026-02-20 00:11:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260220_0011"
down_revision = "20260220_0010"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: Inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if not _has_table(inspector, "reconciliation_suggestions"):
        op.create_table(
            "reconciliation_suggestions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("message_id", sa.BigInteger(), nullable=False),
            sa.Column("transaction_id", sa.BigInteger(), nullable=True),
            sa.Column("category", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("reasoning", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="check_reconcile_suggestion_status"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_reconcile_sug_task", "reconciliation_suggestions", ["task_id"], unique=False)
        op.create_index("idx_reconcile_sug_chat_msg", "reconciliation_suggestions", ["chat_id", "message_id"], unique=False)
        op.create_index("idx_reconcile_sug_category", "reconciliation_suggestions", ["category"], unique=False)
        op.create_index("idx_reconcile_sug_tx", "reconciliation_suggestions", ["transaction_id"], unique=False)
    else:
        if not _has_index(inspector, "reconciliation_suggestions", "idx_reconcile_sug_task"):
            op.create_index("idx_reconcile_sug_task", "reconciliation_suggestions", ["task_id"], unique=False)
        if not _has_index(inspector, "reconciliation_suggestions", "idx_reconcile_sug_chat_msg"):
            op.create_index("idx_reconcile_sug_chat_msg", "reconciliation_suggestions", ["chat_id", "message_id"], unique=False)
        if not _has_index(inspector, "reconciliation_suggestions", "idx_reconcile_sug_category"):
            op.create_index("idx_reconcile_sug_category", "reconciliation_suggestions", ["category"], unique=False)
        if not _has_index(inspector, "reconciliation_suggestions", "idx_reconcile_sug_tx"):
            op.create_index("idx_reconcile_sug_tx", "reconciliation_suggestions", ["transaction_id"], unique=False)

    if not _has_table(inspector, "duplicate_suggestions"):
        op.create_table(
            "duplicate_suggestions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=True),
            sa.Column("primary_transaction_id", sa.BigInteger(), nullable=False),
            sa.Column("duplicate_transaction_id", sa.BigInteger(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("reasoning", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="check_duplicate_suggestion_status"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("primary_transaction_id", "duplicate_transaction_id", name="uq_duplicate_pair"),
        )
        op.create_index("idx_duplicate_sug_task", "duplicate_suggestions", ["task_id"], unique=False)
        op.create_index("idx_duplicate_sug_status", "duplicate_suggestions", ["status"], unique=False)
        op.create_index("idx_duplicate_sug_primary", "duplicate_suggestions", ["primary_transaction_id"], unique=False)
        op.create_index("idx_duplicate_sug_dup", "duplicate_suggestions", ["duplicate_transaction_id"], unique=False)
    else:
        if not _has_index(inspector, "duplicate_suggestions", "idx_duplicate_sug_task"):
            op.create_index("idx_duplicate_sug_task", "duplicate_suggestions", ["task_id"], unique=False)
        if not _has_index(inspector, "duplicate_suggestions", "idx_duplicate_sug_status"):
            op.create_index("idx_duplicate_sug_status", "duplicate_suggestions", ["status"], unique=False)
        if not _has_index(inspector, "duplicate_suggestions", "idx_duplicate_sug_primary"):
            op.create_index("idx_duplicate_sug_primary", "duplicate_suggestions", ["primary_transaction_id"], unique=False)
        if not _has_index(inspector, "duplicate_suggestions", "idx_duplicate_sug_dup"):
            op.create_index("idx_duplicate_sug_dup", "duplicate_suggestions", ["duplicate_transaction_id"], unique=False)

    if not _has_table(inspector, "automation_agent_configs"):
        op.create_table(
            "automation_agent_configs",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("agent_name", sa.String(length=80), nullable=False),
            sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("updated_by", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("agent_name", name="uq_automation_agent_configs_agent_name"),
        )
        op.create_index("idx_automation_agent_cfg_name", "automation_agent_configs", ["agent_name"], unique=False)
        op.create_index("idx_automation_agent_cfg_active", "automation_agent_configs", ["is_active"], unique=False)
    else:
        if not _has_index(inspector, "automation_agent_configs", "idx_automation_agent_cfg_name"):
            op.create_index("idx_automation_agent_cfg_name", "automation_agent_configs", ["agent_name"], unique=False)
        if not _has_index(inspector, "automation_agent_configs", "idx_automation_agent_cfg_active"):
            op.create_index("idx_automation_agent_cfg_active", "automation_agent_configs", ["is_active"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_table(inspector, "automation_agent_configs"):
        for idx in ("idx_automation_agent_cfg_active", "idx_automation_agent_cfg_name"):
            if _has_index(inspector, "automation_agent_configs", idx):
                op.drop_index(idx, table_name="automation_agent_configs")
        op.drop_table("automation_agent_configs")

    if _has_table(inspector, "duplicate_suggestions"):
        for idx in ("idx_duplicate_sug_dup", "idx_duplicate_sug_primary", "idx_duplicate_sug_status", "idx_duplicate_sug_task"):
            if _has_index(inspector, "duplicate_suggestions", idx):
                op.drop_index(idx, table_name="duplicate_suggestions")
        op.drop_table("duplicate_suggestions")

    if _has_table(inspector, "reconciliation_suggestions"):
        for idx in ("idx_reconcile_sug_tx", "idx_reconcile_sug_category", "idx_reconcile_sug_chat_msg", "idx_reconcile_sug_task"):
            if _has_index(inspector, "reconciliation_suggestions", idx):
                op.drop_index(idx, table_name="reconciliation_suggestions")
        op.drop_table("reconciliation_suggestions")
