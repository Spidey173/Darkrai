from typing import List, Optional, TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import String, BigInteger, Text, Boolean
from backend.app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.user import User
    from backend.app.models.rule import Rule
    from backend.app.models.event import WebhookEvent

class Repository(Base, TimestampMixin):
    """GitHub Repositories connected and monitored by the user."""
    __tablename__ = "repositories"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    github_repo_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    webhook_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    webhook_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slack_webhook_url_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="repositories")
    rules: Mapped[List["Rule"]] = relationship(
        "Rule", back_populates="repository", cascade="all, delete-orphan"
    )
    webhook_events: Mapped[List["WebhookEvent"]] = relationship(
        "WebhookEvent", back_populates="repository", cascade="all, delete"
    )
