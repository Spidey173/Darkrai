from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class RepositoryConnect(BaseModel):
    """Payload to connect a new GitHub repository."""
    github_repo_id: int
    name: str
    owner: str
    full_name: str
    slack_webhook_url: Optional[str] = None

class RepositoryResponse(BaseModel):
    """Schema representing connected repository details returned to dashboard."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    github_repo_id: int
    name: str
    owner: str
    full_name: str
    is_active: bool
    webhook_id: Optional[int] = None
    slack_webhook_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class GitHubRepoResponse(BaseModel):
    """Schema representing repository options fetched directly from GitHub API."""
    github_repo_id: int
    name: str
    owner: str
    full_name: str
    description: Optional[str] = None
    private: bool
