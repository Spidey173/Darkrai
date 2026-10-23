"""add worker lease and idempotency

Revision ID: 63c7e18a9bcd
Revises: 52b6b461cda0
Create Date: 2026-10-24 03:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '63c7e18a9bcd'
down_revision = '52b6b461cda0'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add worker_id and lease_expires_at to webhook_events
    op.add_column('webhook_events', sa.Column('worker_id', sa.String(length=100), nullable=True))
    op.add_column('webhook_events', sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('idx_webhook_events_lease', 'webhook_events', ['status', 'lease_expires_at'])

    # Add idempotency_key to action_logs
    op.add_column('action_logs', sa.Column('idempotency_key', sa.String(length=128), nullable=True))
    op.create_index('idx_action_logs_idempotency_key', 'action_logs', ['idempotency_key'])

def downgrade() -> None:
    op.drop_index('idx_action_logs_idempotency_key', table_name='action_logs')
    op.drop_column('action_logs', 'idempotency_key')
    op.drop_index('idx_webhook_events_lease', table_name='webhook_events')
    op.drop_column('webhook_events', 'lease_expires_at')
    op.drop_column('webhook_events', 'worker_id')
