"""create initial tenant user transaction schema

Revision ID: 20260730_0001
Revises:
Create Date: 2026-07-30 08:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260730_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    role_enum = sa.Enum("OWNER", "EMPLOYEE", name="roleenum")
    transaction_type_enum = sa.Enum("INCOME", "EXPENSE", name="transactiontypeenum")
    role_enum.create(op.get_bind(), checkfirst=True)
    transaction_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_name", sa.String(), nullable=False),
        sa.Column("subscription_tier", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("whatsapp_number", sa.String(), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("whatsapp_number"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", transaction_type_enum, nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("raw_image_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transactions_tenant_id"), "transactions", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_transactions_tenant_id"), table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("users")
    op.drop_table("tenants")

    transaction_type_enum = sa.Enum("INCOME", "EXPENSE", name="transactiontypeenum")
    role_enum = sa.Enum("OWNER", "EMPLOYEE", name="roleenum")
    transaction_type_enum.drop(op.get_bind(), checkfirst=True)
    role_enum.drop(op.get_bind(), checkfirst=True)
