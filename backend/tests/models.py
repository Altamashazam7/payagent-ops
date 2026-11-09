"""Small ORM entity used by repository tests."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class SampleEntity(BaseModel):
    """Small mapped entity used to verify repository behavior."""

    __tablename__ = "sample_entities"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
