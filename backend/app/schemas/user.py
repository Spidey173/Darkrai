from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr

class UserBase(BaseModel):
    github_username: str
    email: Optional[EmailStr] = None
    avatar_url: Optional[str] = None

class UserResponse(UserBase):
    """Schema representing user profile details returned to the dashboard."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    github_user_id: int
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
