import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.api.deps import get_db, get_current_user
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.rule import Rule
from backend.app.schemas.rule import RuleCreate, RuleResponse

logger = logging.getLogger("app.api.v1.rules")
router = APIRouter()

async def _get_user_repository(repo_id: UUID, user_id: UUID, db: AsyncSession) -> Repository:
    """Helper to verify that a repository exists and is owned by the current authenticated user."""
    result = await db.execute(
        select(Repository).where(Repository.id == repo_id, Repository.user_id == user_id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found or access denied."
        )
    return repo

@router.get("/repos/{repo_id}/rules", response_model=List[RuleResponse])
async def list_repository_rules(
    repo_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[Rule]:
    """Returns the list of automation rules for the connected repository."""
    await _get_user_repository(repo_id, current_user.id, db)
    
    result = await db.execute(
        select(Rule).where(Rule.repository_id == repo_id).order_by(Rule.created_at.desc())
    )
    return result.scalars().all()

@router.post("/repos/{repo_id}/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_repository_rule(
    repo_id: UUID,
    payload: RuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Rule:
    """Creates a custom automation rule for a connected repository."""
    await _get_user_repository(repo_id, current_user.id, db)
    
    new_rule = Rule(
        repository_id=repo_id,
        name=payload.name,
        event_type=payload.event_type,
        conditions=payload.conditions,
        actions=payload.actions,
        is_active=True
    )
    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)
    return new_rule

@router.patch("/rules/{rule_id}/toggle", response_model=RuleResponse)
async def toggle_rule_activation(
    rule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Rule:
    """Toggles the active state of an automation rule."""
    # Find rule and verify repository ownership
    result = await db.execute(
        select(Rule)
        .join(Repository, Rule.repository_id == Repository.id)
        .where(Rule.id == rule_id, Repository.user_id == current_user.id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found or access denied."
        )

    rule.is_active = not rule.is_active
    await db.commit()
    await db.refresh(rule)
    return rule

@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository_rule(
    rule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> None:
    """Permanently deletes an automation rule."""
    result = await db.execute(
        select(Rule)
        .join(Repository, Rule.repository_id == Repository.id)
        .where(Rule.id == rule_id, Repository.user_id == current_user.id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found or access denied."
        )

    await db.delete(rule)
    await db.commit()
    return None
