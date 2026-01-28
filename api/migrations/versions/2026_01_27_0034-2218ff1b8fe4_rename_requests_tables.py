"""rename requests tables

Revision ID: 2218ff1b8fe4
Revises: 609a42069405
Create Date: 2026-01-27 00:34:32.271719

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2218ff1b8fe4'
down_revision: Union[str, Sequence[str], None] = '609a42069405'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table('refund_request', 'refund_notification_request')
    op.rename_table('charge_request', 'charge_notification_request')


def downgrade() -> None:
    op.rename_table('refund_notification_request', 'refund_request')
    op.rename_table('charge_notification_request', 'charge_request')
