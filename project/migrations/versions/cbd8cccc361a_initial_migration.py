"""Initial migration

Revision ID: cbd8cccc361a
Revises: 2043cb9c9eae
Create Date: 2025-01-26 05:52:21.417293

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel             # NEW


# revision identifiers, used by Alembic.
revision = 'cbd8cccc361a'
down_revision = '2043cb9c9eae'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
