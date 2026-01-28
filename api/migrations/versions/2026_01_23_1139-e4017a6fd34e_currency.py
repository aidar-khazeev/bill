"""currency

Revision ID: e4017a6fd34e
Revises: 2e747cbe7c47
Create Date: 2026-01-23 11:39:02.936259

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4017a6fd34e'
down_revision: Union[str, Sequence[str], None] = '2e747cbe7c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('payment', column_name='roubles', new_column_name='amount')
    op.add_column('payment', sa.Column('currency', sa.String(), nullable=False, server_default='RUB'))


def downgrade() -> None:
    # Not taking exchange rates into account, don't care
    op.alter_column('payment', column_name='amount', new_column_name='roubles')
    op.drop_column('payment', 'currency')
