"""Organisation hierarchy: HO -> Division -> District -> Branch (plan D1)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.types import BranchCategory
from app.models.base import AuthorshipMixin, Base, TimestampMixin, pg_enum


class Division(Base, TimestampMixin, AuthorshipMixin):
    __tablename__ = "divisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    districts: Mapped[list["District"]] = relationship(back_populates="division")


class District(Base, TimestampMixin, AuthorshipMixin):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    division_id: Mapped[int] = mapped_column(ForeignKey("divisions.id"), index=True)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    division: Mapped[Division] = relationship(back_populates="districts")
    branches: Mapped[list["Branch"]] = relationship(back_populates="district")


class Branch(Base, TimestampMixin, AuthorshipMixin):
    """A branch, carrying both its district and its division.

    `division_id` is derivable through `district_id`, but every dashboard query
    filters on it, so it is denormalised. A BEFORE INSERT OR UPDATE trigger
    derives it from the district (see the initial migration), which means the
    two can never disagree -- the redundancy is safe because the database
    maintains it rather than the application.
    """

    __tablename__ = "branches"
    __table_args__ = (
        Index("ix_branches_division_district", "division_id", "district_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    branch_name: Mapped[str] = mapped_column(String(120))
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"), index=True)
    #: Maintained by trigger; nullable at the ORM level so inserts need not set it.
    division_id: Mapped[int | None] = mapped_column(ForeignKey("divisions.id"), index=True)
    category: Mapped[BranchCategory] = mapped_column(
        pg_enum(BranchCategory, "branch_category")
    )
    opened_on: Mapped[date | None] = mapped_column(Date)
    #: Branches are deactivated, never deleted -- fact rows reference them forever.
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    udf: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    district: Mapped[District] = relationship(back_populates="branches")
