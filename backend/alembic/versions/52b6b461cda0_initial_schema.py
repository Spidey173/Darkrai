"""initial database schema

Revision ID: 52b6b461cda0
Revises: 
Create Date: 2026-07-03 17:36:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '52b6b461cda0'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Enable UUID Extension
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # 2. Create "users" Table
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('github_user_id', sa.BigInteger(), nullable=False),
        sa.Column('github_username', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('avatar_url', sa.String(length=255), nullable=True),
        sa.Column('github_access_token_encrypted', sa.Text(), nullable=False),
        sa.Column('github_refresh_token_encrypted', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('github_user_id')
    )

    # 3. Create "repositories" Table
    op.create_table(
        'repositories',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('github_repo_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('owner', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('webhook_id', sa.BigInteger(), nullable=True),
        sa.Column('webhook_secret_encrypted', sa.Text(), nullable=True),
        sa.Column('slack_webhook_url_encrypted', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('github_repo_id')
    )
    op.create_index('idx_repositories_user_id', 'repositories', ['user_id'])
    op.create_index('idx_repositories_owner_name', 'repositories', ['owner', 'name'])

    # 4. Create "rules" Table
    op.create_table(
        'rules',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('actions', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_rules_repository_id', 'rules', ['repository_id'])
    op.create_index(
        'idx_rules_repo_event_active', 
        'rules', 
        ['repository_id', 'event_type'], 
        postgresql_where=sa.text('is_active = TRUE')
    )

    # 5. Create "webhook_events" Table
    op.create_table(
        'webhook_events',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=True),
        sa.Column('delivery_id', sa.UUID(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('delivery_id')
    )
    op.create_index('idx_webhook_events_repository_id', 'webhook_events', ['repository_id'])
    op.create_index('idx_webhook_events_status', 'webhook_events', ['status'])

    # 6. Create "action_logs" Table
    op.create_table(
        'action_logs',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('webhook_event_id', sa.UUID(), nullable=False),
        sa.Column('rule_id', sa.UUID(), nullable=True),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['rule_id'], ['rules.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['webhook_event_id'], ['webhook_events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_action_logs_webhook_event_id', 'action_logs', ['webhook_event_id'])
    op.create_index('idx_action_logs_rule_id', 'action_logs', ['rule_id'])

def downgrade() -> None:
    op.drop_index('idx_action_logs_rule_id', table_name='action_logs')
    op.drop_index('idx_action_logs_webhook_event_id', table_name='action_logs')
    op.drop_table('action_logs')
    op.drop_index('idx_webhook_events_status', table_name='webhook_events')
    op.drop_index('idx_webhook_events_repository_id', table_name='webhook_events')
    op.drop_table('webhook_events')
    op.drop_index('idx_rules_repo_event_active', table_name='rules')
    op.drop_index('idx_rules_repository_id', table_name='rules')
    op.drop_table('rules')
    op.drop_index('idx_repositories_owner_name', table_name='repositories')
    op.drop_index('idx_repositories_user_id', table_name='repositories')
    op.drop_table('repositories')
    op.drop_table('users')
