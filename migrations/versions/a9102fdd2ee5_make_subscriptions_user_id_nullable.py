"""make subscriptions user_id nullable

Revision ID: a9102fdd2ee5
Revises: 
Create Date: 2026-02-17 19:11:30.426318

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9102fdd2ee5'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'users' not in existing_tables:
        op.create_table(
            'users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('username', sa.String(length=150), nullable=False),
            sa.Column('password_hash', sa.String(length=255), nullable=False),
            sa.Column('role', sa.String(length=50), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('username')
        )
        op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=False)

    if 'subscription_plans' not in existing_tables:
        op.create_table(
            'subscription_plans',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('trays_per_week', sa.Integer(), nullable=False),
            sa.Column('price_per_month', sa.Float(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('is_recommended', sa.Boolean(), nullable=False),
            sa.Column('button_color', sa.String(length=20), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name')
        )

    if 'subscriptions' not in existing_tables:
        op.create_table(
            'subscriptions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('plan_id', sa.Integer(), nullable=False),
            sa.Column('start_date', sa.DateTime(), nullable=False),
            sa.Column('next_delivery_date', sa.DateTime(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('preferred_delivery_day', sa.String(length=20), nullable=False),
            sa.Column('checkout_request_id', sa.String(length=50), nullable=True),
            sa.Column('phone', sa.String(length=20), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('location', sa.String(length=200), nullable=False),
            sa.ForeignKeyConstraint(['plan_id'], ['subscription_plans.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id')
        )

    if 'payments' not in existing_tables:
        op.create_table(
            'payments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('subscription_id', sa.Integer(), nullable=False),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('mpesa_receipt', sa.String(length=50), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=False),
            sa.Column('payment_date', sa.DateTime(), nullable=True),
            sa.Column('checkout_request_id', sa.String(length=100), nullable=True),
            sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_payments_checkout_request_id'), 'payments', ['checkout_request_id'], unique=False)
        op.create_index(op.f('ix_payments_subscription_id'), 'payments', ['subscription_id'], unique=False)

    if 'deliveries' not in existing_tables:
        op.create_table(
            'deliveries',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('subscription_id', sa.Integer(), nullable=False),
            sa.Column('scheduled_date', sa.DateTime(), nullable=False),
            sa.Column('status', sa.String(length=50), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_deliveries_subscription_id'), 'deliveries', ['subscription_id'], unique=False)

    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.alter_column(
            'user_id',
            existing_type=sa.Integer(),
            nullable=True
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'subscriptions' in existing_tables:
        with op.batch_alter_table('subscriptions', schema=None) as batch_op:
            batch_op.alter_column(
                'user_id',
                existing_type=sa.Integer(),
                nullable=False
            )
