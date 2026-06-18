"""add case_photos table and doctor photo_url

Revision ID: 137b09c5062e
Revises: 4ae928e4c7bb
Create Date: 2026-06-17 21:53:45.399474

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '137b09c5062e'
down_revision: Union[str, Sequence[str], None] = '4ae928e4c7bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """case_photosテーブル新設 + doctors.photo_urlカラム追加"""
    # 症例写真テーブル新設
    op.create_table('case_photos',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('clinic_id', sa.String(length=26), nullable=True),
    sa.Column('doctor_id', sa.String(length=26), nullable=True),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('procedure_name', sa.String(length=200), nullable=True),
    sa.Column('before_image_url', sa.String(length=500), nullable=True),
    sa.Column('after_image_url', sa.String(length=500), nullable=True),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('price', sa.String(length=100), nullable=True),
    sa.Column('doctor_name', sa.String(length=100), nullable=True),
    sa.Column('clinic_name', sa.String(length=200), nullable=True),
    sa.Column('source_case_id', sa.String(length=100), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('fetched_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['clinic_id'], ['clinics.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_case_photos_category', 'case_photos', ['category'], unique=False)
    op.create_index('ix_case_photos_clinic', 'case_photos', ['clinic_id'], unique=False)
    op.create_index('ix_case_photos_doctor', 'case_photos', ['doctor_id'], unique=False)
    op.create_index('ix_case_photos_source', 'case_photos', ['source'], unique=False)
    op.create_index('ix_case_photos_source_id', 'case_photos', ['source_case_id'], unique=False)

    # 医師テーブルにプロフィール写真URLカラム追加
    op.add_column('doctors', sa.Column('photo_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """ロールバック"""
    op.drop_column('doctors', 'photo_url')
    op.drop_index('ix_case_photos_source_id', table_name='case_photos')
    op.drop_index('ix_case_photos_source', table_name='case_photos')
    op.drop_index('ix_case_photos_doctor', table_name='case_photos')
    op.drop_index('ix_case_photos_clinic', table_name='case_photos')
    op.drop_index('ix_case_photos_category', table_name='case_photos')
    op.drop_table('case_photos')
