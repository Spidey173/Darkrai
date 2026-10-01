from typing import List, Dict, Any, TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import String, Boolean, JSON
from backend.app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.repository import Repository
    from backend.app.models.action_log import ActionLog

class Rule(Base, TimestampMixin):
    """User-defined automation rule evaluating webhook conditions to execute specific actions."""
    __tablename__ = "rules"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False) # e.g. "issues"
    
    # Store conditions & actions as schema-flexible JSON/JSONB
    conditions: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    actions: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    repository: Mapped["Repository"] = relationship("Repository", back_populates="rules")
    action_logs: Mapped[List["ActionLog"]] = relationship("ActionLog", back_populates="rule")
