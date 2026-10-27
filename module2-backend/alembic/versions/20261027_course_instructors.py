"""Add course_instructors and backfill from session owners.

Revision ID: 20261027_ci
Revises:
Create Date: 2026-10-27
"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261027_ci"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "course_instructors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("instructor_id", sa.String(length=36), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("assigned_by_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["instructor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "instructor_id", name="uq_course_instructor"),
    )
    op.create_index(
        op.f("ix_course_instructors_course_id"),
        "course_instructors",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_course_instructors_instructor_id"),
        "course_instructors",
        ["instructor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_course_instructors_is_active"),
        "course_instructors",
        ["is_active"],
        unique=False,
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT DISTINCT s.course_id, s.instructor_id
            FROM sessions s
            WHERE s.instructor_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM course_instructors ci
                WHERE ci.course_id = s.course_id AND ci.instructor_id = s.instructor_id
              )
            """
        )
    ).fetchall()
    assigned_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for course_id, instructor_id in rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO course_instructors
                    (id, course_id, instructor_id, is_active, assigned_at)
                VALUES
                    (:id, :course_id, :instructor_id, TRUE, :assigned_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "course_id": course_id,
                "instructor_id": instructor_id,
                "assigned_at": assigned_at,
            },
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_course_instructors_is_active"), table_name="course_instructors")
    op.drop_index(op.f("ix_course_instructors_instructor_id"), table_name="course_instructors")
    op.drop_index(op.f("ix_course_instructors_course_id"), table_name="course_instructors")
    op.drop_table("course_instructors")
