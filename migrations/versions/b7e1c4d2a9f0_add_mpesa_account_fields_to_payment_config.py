"""add mpesa account fields to payment config

Revision ID: b7e1c4d2a9f0
Revises: 9c4a6d2b1e7f
Create Date: 2026-02-19 14:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b7e1c4d2a9f0"
down_revision = "9c4a6d2b1e7f"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "payment_configs" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("payment_configs")}
    with op.batch_alter_table("payment_configs", schema=None) as batch_op:
        if "mpesa_account_name" not in columns:
            batch_op.add_column(sa.Column("mpesa_account_name", sa.String(length=100), nullable=True))
        if "mpesa_account_number" not in columns:
            batch_op.add_column(sa.Column("mpesa_account_number", sa.String(length=80), nullable=True))

    bind.execute(sa.text("""
        UPDATE payment_configs
        SET mpesa_account_name = COALESCE(NULLIF(mpesa_account_name, ''), bank_account_name, 'NestGold Provisions'),
            mpesa_account_number = COALESCE(NULLIF(mpesa_account_number, ''), bank_account_number, '1234567890')
    """))

    with op.batch_alter_table("payment_configs", schema=None) as batch_op:
        batch_op.alter_column("mpesa_account_name", existing_type=sa.String(length=100), nullable=False)
        batch_op.alter_column("mpesa_account_number", existing_type=sa.String(length=80), nullable=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "payment_configs" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("payment_configs")}
    with op.batch_alter_table("payment_configs", schema=None) as batch_op:
        if "mpesa_account_number" in columns:
            batch_op.drop_column("mpesa_account_number")
        if "mpesa_account_name" in columns:
            batch_op.drop_column("mpesa_account_name")
