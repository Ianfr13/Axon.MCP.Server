"""Add GitHub provider support

Revision ID: 016_add_github_support
Revises: 015_add_complexity_index
Create Date: 2026-02-23 12:10:00.000000

Adds GITHUB value to sourcecontrolproviderenum and GitHub-specific columns
to the repositories table (github_repo_id, github_owner).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '016_add_github_support'
down_revision = '015_add_complexity_index'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add GitHub support: enum value + columns + index."""

    # 1. Add 'github' to the existing provider enum
    op.execute("ALTER TYPE sourcecontrolproviderenum ADD VALUE IF NOT EXISTS 'GITHUB'")

    # 2. Add GitHub-specific columns
    op.add_column('repositories', sa.Column('github_repo_id', sa.Integer(), nullable=True))
    op.add_column('repositories', sa.Column('github_owner', sa.String(length=255), nullable=True))

    # 3. Create composite index
    op.create_index('idx_repo_github_owner_id', 'repositories', ['github_owner', 'github_repo_id'])


def downgrade() -> None:
    """Remove GitHub support columns and index."""

    # Drop index
    op.drop_index('idx_repo_github_owner_id', table_name='repositories')

    # Drop columns
    op.drop_column('repositories', 'github_owner')
    op.drop_column('repositories', 'github_repo_id')

    # NOTE: PostgreSQL does not support removing enum values.
    # The 'GITHUB' value remains in the enum after downgrade.
