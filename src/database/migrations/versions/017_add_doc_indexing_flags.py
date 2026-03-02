"""Add document indexing flags to repositories

Revision ID: 017_add_doc_indexing_flags
Revises: 016_add_github_support
Create Date: 2026-03-02 21:00:00.000000

Adds index_md_files and index_txt_files boolean columns to repositories table
for per-repo control over which document types are indexed during sync.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '017_add_doc_indexing_flags'
down_revision = '016_add_github_support'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add document indexing flag columns with defaults."""
    op.add_column('repositories', sa.Column(
        'index_md_files', sa.Boolean(), nullable=False, server_default='true'
    ))
    op.add_column('repositories', sa.Column(
        'index_txt_files', sa.Boolean(), nullable=False, server_default='false'
    ))


def downgrade() -> None:
    """Remove document indexing flag columns."""
    op.drop_column('repositories', 'index_txt_files')
    op.drop_column('repositories', 'index_md_files')
