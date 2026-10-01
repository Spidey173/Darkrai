from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import String, BigInteger, Text, DateTime
from backend.app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.repository import Repository

class User(Base, TimestampMixin):
    """User representation representing registered user with GitHub OAuth configuration."""
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    github_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    github_username: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Encrypted fields to secure API access
    github_access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    github_refresh_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    repositories: Mapped[List["Repository"]] = relationship(
        "Repository", back_populates="user", cascade="all, delete-orphan"
    )
