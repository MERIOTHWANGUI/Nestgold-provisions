"""manual payment workflow fields

Revision ID: f3b2e7a9c1d0
Revises: e42c9d19f1ab
Create Date: 2026-02-19 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f3b2e7a9c1d0"
down_revision = "e42c9d19f1ab"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "subscriptions" in tables:
        columns = {c["name"] for c in inspector.get_columns("subscriptions")}
        with op.batch_alter_table("subscriptions", schema=None) as batch_op:
            if "delivery_status" not in columns:
                batch_op.add_column(
                    sa.Column("delivery_status", sa.String(length=30), nullable=True, server_default="Pending")
                )
        bind.execute(sa.text("UPDATE subscriptions SET delivery_status='Pending' WHERE delivery_status IS NULL"))
        with op.batch_alter_table("subscriptions", schema=None) as batch_op:
            batch_op.alter_column(
                "delivery_status",
                existing_type=sa.String(length=30),
                nullable=False,
                server_default="Pending",
            )

    if "payments" in tables:
        columns = {c["name"] for c in inspector.get_columns("payments")}
        indexes = {i["name"] for i in inspector.get_indexes("payments")}
        with op.batch_alter_table("payments", schema=None) as batch_op:
            if "manual_payment_status" not in columns:
                batch_op.add_column(
                    sa.Column("manual_payment_status", sa.String(length=20), nullable=True, server_default="Pending")
                )
            if "tracking_code" not in columns:
                batch_op.add_column(sa.Column("tracking_code", sa.String(length=40), nullable=True))
            if "reference_id" not in columns:
                batch_op.add_column(sa.Column("reference_id", sa.String(length=80), nullable=True))
            if "customer_name" not in columns:
                batch_op.add_column(sa.Column("customer_name", sa.String(length=100), nullable=True))
            if "customer_phone" not in columns:
                batch_op.add_column(sa.Column("customer_phone", sa.String(length=20), nullable=True))
            if "description" not in columns:
                batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
            if "instruction_channel" not in columns:
                batch_op.add_column(sa.Column("instruction_channel", sa.String(length=20), nullable=True))

        bind.execute(sa.text("UPDATE payments SET manual_payment_status='Pending' WHERE manual_payment_status IS NULL"))
        with op.batch_alter_table("payments", schema=None) as batch_op:
            batch_op.alter_column(
                "manual_payment_status",
                existing_type=sa.String(length=20),
                nullable=False,
                server_default="Pending",
            )
            if "ix_payments_tracking_code" not in indexes:
                batch_op.create_index("ix_payments_tracking_code", ["tracking_code"], unique=True)
            if "ix_payments_reference_id" not in indexes:
                batch_op.create_index("ix_payments_reference_id", ["reference_id"], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "payments" in tables:
        indexes = {i["name"] for i in inspector.get_indexes("payments")}
        with op.batch_alter_table("payments", schema=None) as batch_op:
            if "ix_payments_tracking_code" in indexes:
                batch_op.drop_index("ix_payments_tracking_code")
            if "ix_payments_reference_id" in indexes:
                batch_op.drop_index("ix_payments_reference_id")
            columns = {c["name"] for c in inspector.get_columns("payments")}
            if "instruction_channel" in columns:
                batch_op.drop_column("instruction_channel")
            if "description" in columns:
                batch_op.drop_column("description")
            if "customer_phone" in columns:
                batch_op.drop_column("customer_phone")
            if "customer_name" in columns:
                batch_op.drop_column("customer_name")
            if "reference_id" in columns:
                batch_op.drop_column("reference_id")
            if "tracking_code" in columns:
                batch_op.drop_column("tracking_code")
            if "manual_payment_status" in columns:
                batch_op.drop_column("manual_payment_status")

    if "subscriptions" in tables:
        columns = {c["name"] for c in inspector.get_columns("subscriptions")}
        if "delivery_status" in columns:
            with op.batch_alter_table("subscriptions", schema=None) as batch_op:
                batch_op.drop_column("delivery_status")
