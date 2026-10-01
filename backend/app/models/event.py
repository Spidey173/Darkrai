from datetime import datetime
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import String, Integer, Text, JSON, DateTime
from backend.app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.repository import Repository
    from backend.app.models.action_log import ActionLog

class WebhookEvent(Base, TimestampMixin):
    """Raw record of received GitHub webhook delivery tracking lifecycle status."""
    __tablename__ = "webhook_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True
    )
    delivery_id: Mapped[UUID] = mapped_column(unique=True, nullable=False) # X-GitHub-Delivery Header
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False) # pending, processing, completed, failed
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    repository: Mapped[Optional["Repository"]] = relationship("Repository", back_populates="webhook_events")
    action_logs: Mapped[List["ActionLog"]] = relationship(
        "ActionLog", back_populates="webhook_event", cascade="all, delete"
    )
