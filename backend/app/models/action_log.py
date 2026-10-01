from datetime import datetime
from typing import Dict, Any, Optional, TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import String, JSON, DateTime
from backend.app.models.base import Base

if TYPE_CHECKING:
    from backend.app.models.event import WebhookEvent
    from backend.app.models.rule import Rule

class ActionLog(Base):
    """Audit trail of execution actions performed by the bot on GitHub or Slack."""
    __tablename__ = "action_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    webhook_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("webhook_events.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("rules.id", ondelete="SET NULL"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False) # e.g. "label", "comment", "slack"
    status: Mapped[str] = mapped_column(String(20), nullable=False) # "success", "failed"
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    webhook_event: Mapped["WebhookEvent"] = relationship("WebhookEvent", back_populates="action_logs")
    rule: Mapped[Optional["Rule"]] = relationship("Rule", back_populates="action_logs")
    
# Import all models here or define __init__.py under models to ensure Alembic is aware of them.
