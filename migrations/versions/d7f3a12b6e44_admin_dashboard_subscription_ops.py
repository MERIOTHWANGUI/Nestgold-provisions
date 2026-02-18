"""add admin dashboard subscription ops fields

Revision ID: d7f3a12b6e44
Revises: c61b5ac8d8f2
Create Date: 2026-02-18 13:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7f3a12b6e44'
down_revision = 'c61b5ac8d8f2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'subscriptions' in tables:
        columns = {c['name'] for c in inspector.get_columns('subscriptions')}
        with op.batch_alter_table('subscriptions', schema=None) as batch_op:
            if 'trays_remaining' not in columns:
                batch_op.add_column(sa.Column('trays_remaining', sa.Integer(), nullable=True, server_default='0'))
            if 'trays_allocated_total' not in columns:
                batch_op.add_column(sa.Column('trays_allocated_total', sa.Integer(), nullable=True, server_default='0'))

        rows = bind.execute(sa.text("""
            SELECT s.id, sp.trays_per_week,
                   COALESCE(SUM(CASE WHEN p.status = 'Completed' THEN 1 ELSE 0 END), 0) AS completed_payments
            FROM subscriptions s
            JOIN subscription_plans sp ON sp.id = s.plan_id
            LEFT JOIN payments p ON p.subscription_id = s.id
            GROUP BY s.id, sp.trays_per_week
        """)).mappings().all()
        for row in rows:
            total_allocated = int(row['completed_payments'] or 0) * int(row['trays_per_week'] or 0) * 4
            bind.execute(
                sa.text("""
                    UPDATE subscriptions
                    SET trays_allocated_total = :v,
                        trays_remaining = :v
                    WHERE id = :sid
                """),
                {'v': total_allocated, 'sid': row['id']}
            )

        with op.batch_alter_table('subscriptions', schema=None) as batch_op:
            batch_op.alter_column('trays_remaining', existing_type=sa.Integer(), nullable=False, server_default='0')
            batch_op.alter_column('trays_allocated_total', existing_type=sa.Integer(), nullable=False, server_default='0')

    if 'payments' in tables:
        columns = {c['name'] for c in inspector.get_columns('payments')}
        with op.batch_alter_table('payments', schema=None) as batch_op:
            if 'payment_method' not in columns:
                batch_op.add_column(sa.Column('payment_method', sa.String(length=30), nullable=True, server_default='M-Pesa'))
        bind.execute(sa.text("UPDATE payments SET payment_method = 'M-Pesa' WHERE payment_method IS NULL OR payment_method = ''"))
        with op.batch_alter_table('payments', schema=None) as batch_op:
            batch_op.alter_column('payment_method', existing_type=sa.String(length=30), nullable=False, server_default='M-Pesa')

    if 'subscription_reminders' not in tables:
        op.create_table(
            'subscription_reminders',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('subscription_id', sa.Integer(), nullable=False),
            sa.Column('reminder_type', sa.String(length=30), nullable=False),
            sa.Column('channel', sa.String(length=20), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('message_preview', sa.String(length=255), nullable=True),
            sa.Column('sent_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('created_by', sa.String(length=100), nullable=True),
            sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_subscription_reminders_subscription_id'), 'subscription_reminders', ['subscription_id'], unique=False)
        op.create_index(op.f('ix_subscription_reminders_created_at'), 'subscription_reminders', ['created_at'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'subscription_reminders' in tables:
        op.drop_index(op.f('ix_subscription_reminders_created_at'), table_name='subscription_reminders')
        op.drop_index(op.f('ix_subscription_reminders_subscription_id'), table_name='subscription_reminders')
        op.drop_table('subscription_reminders')

    if 'payments' in tables:
        columns = {c['name'] for c in inspector.get_columns('payments')}
        if 'payment_method' in columns:
            with op.batch_alter_table('payments', schema=None) as batch_op:
                batch_op.drop_column('payment_method')

    if 'subscriptions' in tables:
        columns = {c['name'] for c in inspector.get_columns('subscriptions')}
        with op.batch_alter_table('subscriptions', schema=None) as batch_op:
            if 'trays_allocated_total' in columns:
                batch_op.drop_column('trays_allocated_total')
            if 'trays_remaining' in columns:
                batch_op.drop_column('trays_remaining')
