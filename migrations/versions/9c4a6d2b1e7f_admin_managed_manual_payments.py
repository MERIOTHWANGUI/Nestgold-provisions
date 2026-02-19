"""admin managed manual payment workflow

Revision ID: 9c4a6d2b1e7f
Revises: f3b2e7a9c1d0
Create Date: 2026-02-19 12:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9c4a6d2b1e7f"
down_revision = "f3b2e7a9c1d0"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "payments" in tables:
        columns = {c["name"] for c in inspector.get_columns("payments")}
        indexes = {i["name"] for i in inspector.get_indexes("payments")}
        with op.batch_alter_table("payments", schema=None) as batch_op:
            if "payment_status" not in columns:
                batch_op.add_column(sa.Column("payment_status", sa.String(length=20), nullable=True, server_default="Pending"))
            if "admin_transaction_reference" not in columns:
                batch_op.add_column(sa.Column("admin_transaction_reference", sa.String(length=100), nullable=True))
            if "admin_notes" not in columns:
                batch_op.add_column(sa.Column("admin_notes", sa.Text(), nullable=True))

        bind.execute(sa.text("""
            UPDATE payments
            SET payment_status = CASE
                WHEN status = 'Completed' OR manual_payment_status = 'Confirmed' THEN 'Confirmed'
                ELSE 'Pending'
            END
            WHERE payment_status IS NULL OR payment_status = ''
        """))

        with op.batch_alter_table("payments", schema=None) as batch_op:
            batch_op.alter_column("payment_status", existing_type=sa.String(length=20), nullable=False, server_default="Pending")
            if "ix_payments_payment_status" not in indexes:
                batch_op.create_index("ix_payments_payment_status", ["payment_status"], unique=False)

    if "payment_configs" not in tables:
        op.create_table(
            "payment_configs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mpesa_paybill", sa.String(length=40), nullable=False),
            sa.Column("bank_name", sa.String(length=100), nullable=False),
            sa.Column("bank_account_name", sa.String(length=100), nullable=False),
            sa.Column("bank_account_number", sa.String(length=80), nullable=False),
            sa.Column("instructions_footer", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        bind.execute(sa.text("""
            INSERT INTO payment_configs (
                mpesa_paybill, bank_name, bank_account_name, bank_account_number, instructions_footer, updated_at
            ) VALUES (
                '174379', 'NestGold Bank', 'NestGold Provisions', '1234567890',
                'After payment, keep your receipt and share it with admin via WhatsApp/SMS/email.',
                CURRENT_TIMESTAMP
            )
        """))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "payment_configs" in tables:
        op.drop_table("payment_configs")

    if "payments" in tables:
        indexes = {i["name"] for i in inspector.get_indexes("payments")}
        columns = {c["name"] for c in inspector.get_columns("payments")}
        with op.batch_alter_table("payments", schema=None) as batch_op:
            if "ix_payments_payment_status" in indexes:
                batch_op.drop_index("ix_payments_payment_status")
            if "admin_notes" in columns:
                batch_op.drop_column("admin_notes")
            if "admin_transaction_reference" in columns:
                batch_op.drop_column("admin_transaction_reference")
            if "payment_status" in columns:
                batch_op.drop_column("payment_status")
