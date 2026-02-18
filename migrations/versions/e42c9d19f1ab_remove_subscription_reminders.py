"""remove subscription reminders table

Revision ID: e42c9d19f1ab
Revises: d7f3a12b6e44
Create Date: 2026-02-18 14:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e42c9d19f1ab'
down_revision = 'd7f3a12b6e44'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'subscription_reminders' in tables:
        indexes = {idx['name'] for idx in inspector.get_indexes('subscription_reminders')}
        if op.f('ix_subscription_reminders_created_at') in indexes:
            op.drop_index(op.f('ix_subscription_reminders_created_at'), table_name='subscription_reminders')
        if op.f('ix_subscription_reminders_subscription_id') in indexes:
            op.drop_index(op.f('ix_subscription_reminders_subscription_id'), table_name='subscription_reminders')
        op.drop_table('subscription_reminders')


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

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
