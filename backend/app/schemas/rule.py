from datetime import datetime
from typing import Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class RuleCreate(BaseModel):
    """Payload to create or update an automation rule."""
    name: str
    event_type: str  # e.g., 'issues' or 'pull_request'
    conditions: Dict[str, Any]  # e.g., {"field": "title", "operator": "contains", "value": "bug"}
    actions: List[Dict[str, Any]]  # e.g., [{"type": "add_label", "value": "bug"}]

class RuleResponse(BaseModel):
    """Schema representing rule detail responses."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repository_id: UUID
    name: str
    event_type: str
    conditions: Dict[str, Any]
    actions: List[Dict[str, Any]]
    is_active: bool
    created_at: datetime
    updated_at: datetime
