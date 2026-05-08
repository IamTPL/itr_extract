"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-08

"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE job_status AS ENUM ('pending', 'processing', 'success', 'failed')")

    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_login', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'processing', 'success', 'failed', name='job_status', create_type=False), nullable=False),
        sa.Column('original_filename', sa.Text(), nullable=False),
        sa.Column('input_size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('analysis_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('email_html', sa.Text(), nullable=True),
        sa.Column('has_econsent', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('parent_job_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['parent_job_id'], ['jobs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('idx_jobs_user_created', 'jobs', ['user_id', sa.text('created_at DESC')])
    op.create_index(
        'idx_jobs_status_active', 'jobs', ['status'],
        postgresql_where=sa.text("status IN ('pending','processing')"),
    )


def downgrade() -> None:
    op.drop_index('idx_jobs_status_active', table_name='jobs')
    op.drop_index('idx_jobs_user_created', table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('users')
    op.execute("DROP TYPE job_status")
