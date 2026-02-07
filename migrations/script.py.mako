"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | n,'None'}
Create Date: ${create_date}
"""
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '${rev_id}'
down_revision: str | None = ${down_revision | n,'None'}
branch_labels: str | None = ${branch_labels | n,'None'}
depends_on: str | None = ${depends_on | n,'None'}


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
