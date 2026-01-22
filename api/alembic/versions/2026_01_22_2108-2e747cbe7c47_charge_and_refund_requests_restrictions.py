"""charge and refund requests restrictions

Revision ID: 2e747cbe7c47
Revises: e61d82c5f571
Create Date: 2026-01-22 21:08:34.514834

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e747cbe7c47'
down_revision: Union[str, Sequence[str], None] = 'e61d82c5f571'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('charge_request', sa.Column('captured', sa.Boolean(), nullable=False))
    op.drop_index(op.f('ix_charge_request_id'), table_name='charge_request')
    op.drop_index(op.f('ix_charge_request_payment_id'), table_name='charge_request')
    op.create_unique_constraint(None, 'charge_request', ['payment_id'])
    op.drop_constraint(op.f('charge_request_payment_id_fkey'), 'charge_request', type_='foreignkey')
    op.create_foreign_key(None, 'charge_request', 'payment', ['payment_id'], ['id'], ondelete='RESTRICT')

    op.add_column('refund_request', sa.Column('refunded', sa.Boolean(), nullable=False))
    op.drop_index(op.f('ix_refund_request_id'), table_name='refund_request')
    op.drop_index(op.f('ix_refund_request_payment_id'), table_name='refund_request')
    op.create_unique_constraint(None, 'refund_request', ['payment_id'])
    op.drop_constraint(op.f('refund_request_payment_id_fkey'), 'refund_request', type_='foreignkey')
    op.create_foreign_key(None, 'refund_request', 'payment', ['payment_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(None, 'refund_request', type_='foreignkey')
    op.create_foreign_key(op.f('refund_request_payment_id_fkey'), 'refund_request', 'payment', ['payment_id'], ['id'])
    op.drop_constraint(None, 'refund_request', type_='unique')
    op.create_index(op.f('ix_refund_request_payment_id'), 'refund_request', ['payment_id'], unique=False)
    op.create_index(op.f('ix_refund_request_id'), 'refund_request', ['id'], unique=False)
    op.drop_column('refund_request', 'refunded')

    op.drop_constraint(None, 'charge_request', type_='foreignkey')
    op.create_foreign_key(op.f('charge_request_payment_id_fkey'), 'charge_request', 'payment', ['payment_id'], ['id'])
    op.drop_constraint(None, 'charge_request', type_='unique')
    op.create_index(op.f('ix_charge_request_payment_id'), 'charge_request', ['payment_id'], unique=False)
    op.create_index(op.f('ix_charge_request_id'), 'charge_request', ['id'], unique=False)
    op.drop_column('charge_request', 'captured')
