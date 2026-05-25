"""add_evidence_publish_clinic_procedures

Revision ID: 4ae928e4c7bb
Revises: 44ce6d75260c
Create Date: 2026-05-24 21:44:26.223358

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ae928e4c7bb'
down_revision: Union[str, Sequence[str], None] = '44ce6d75260c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # clinic_procedures 新テーブル作成（FK・ユニーク制約・インデックスは定義に含まれる）
    op.create_table('clinic_procedures',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('clinic_id', sa.String(length=26), nullable=False),
    sa.Column('procedure_id', sa.String(length=26), nullable=False),
    sa.Column('price_advertised', sa.Integer(), nullable=True),
    sa.Column('price_actual', sa.Integer(), nullable=True),
    sa.Column('price_display', sa.String(length=100), nullable=True),
    sa.Column('source', sa.String(length=50), nullable=True),
    sa.Column('fetched_at', sa.DateTime(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['clinic_id'], ['clinics.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['procedure_id'], ['procedures.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('clinic_id', 'procedure_id', name='uq_clinic_procedure')
    )
    op.create_index(op.f('ix_clinic_procedures_clinic_id'), 'clinic_procedures', ['clinic_id'], unique=False)
    op.create_index('ix_cp_procedure', 'clinic_procedures', ['procedure_id'], unique=False)

    # clinics: publish_status カラム追加
    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.add_column(sa.Column('publish_status', sa.String(length=20), nullable=True))

    # procedures: データ品質管理カラム4つ追加
    with op.batch_alter_table('procedures', schema=None) as batch_op:
        batch_op.add_column(sa.Column('evidence_level', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('price_sources', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('last_verified_date', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('publish_status', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('procedures', schema=None) as batch_op:
        batch_op.drop_column('publish_status')
        batch_op.drop_column('last_verified_date')
        batch_op.drop_column('price_sources')
        batch_op.drop_column('evidence_level')

    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.drop_column('publish_status')

    op.drop_index('ix_cp_procedure', table_name='clinic_procedures')
    op.drop_index(op.f('ix_clinic_procedures_clinic_id'), table_name='clinic_procedures')
    op.drop_table('clinic_procedures')
