import logging
import secrets
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.api.deps import get_db, get_current_user
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.schemas.repository import RepositoryConnect, RepositoryResponse, GitHubRepoResponse
from backend.app.services.encryption import encrypt_token, decrypt_token
from backend.app.services.github_client import GitHubClient

logger = logging.getLogger("app.api.v1.repos")
router = APIRouter()

@router.get("/github", response_model=List[GitHubRepoResponse])
async def list_github_repositories(
    current_user: User = Depends(get_current_user)
) -> List[dict]:
    """Queries GitHub REST API to list repositories owned by the current authenticated user."""
    github_token = decrypt_token(current_user.github_access_token_encrypted)
    try:
        raw_repos = await GitHubClient.list_user_repos(github_token)
        
        parsed_repos = []
        for repo in raw_repos:
            parsed_repos.append({
                "github_repo_id": repo["id"],
                "name": repo["name"],
                "owner": repo["owner"]["login"],
                "full_name": repo["full_name"],
                "description": repo.get("description"),
                "private": repo["private"],
            })
        return parsed_repos
    except Exception as e:
        logger.error("Failed to query user GitHub repos: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to retrieve repositories from GitHub API."
        )

@router.get("", response_model=List[RepositoryResponse])
async def list_connected_repositories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[Repository]:
    """Returns connected repositories currently monitored in Postgres for the current user."""
    result = await db.execute(
        select(Repository).where(Repository.user_id == current_user.id)
    )
    repos = result.scalars().all()
    
    # Decrypt slack webhooks for representation if desired
    for repo in repos:
        if repo.slack_webhook_url_encrypted:
            repo.slack_webhook_url = decrypt_token(repo.slack_webhook_url_encrypted)
            
    return repos

@router.post("/connect", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def connect_repository(
    payload: RepositoryConnect,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Repository:
    """Saves repository connection details."""
    # 1. Prevent duplicate connections
    dup_result = await db.execute(
        select(Repository).where(Repository.github_repo_id == payload.github_repo_id)
    )
    if dup_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository is already connected."
        )

    # 2. Encrypt Slack Webhook if provided
    encrypted_slack_url = None
    if payload.slack_webhook_url:
        encrypted_slack_url = encrypt_token(payload.slack_webhook_url)

    # 3. Generate random webhook signing secret
    webhook_secret = secrets.token_hex(20)
    encrypted_webhook_secret = encrypt_token(webhook_secret)

    # 4. Save connected repository record
    new_repo = Repository(
        user_id=current_user.id,
        github_repo_id=payload.github_repo_id,
        name=payload.name,
        owner=payload.owner,
        full_name=payload.full_name,
        is_active=False,  # Start inactive until webhook registration is enabled
        webhook_secret_encrypted=encrypted_webhook_secret,
        slack_webhook_url_encrypted=encrypted_slack_url
    )
    db.add(new_repo)
    await db.commit()
    await db.refresh(new_repo)

    if new_repo.slack_webhook_url_encrypted:
        new_repo.slack_webhook_url = decrypt_token(new_repo.slack_webhook_url_encrypted)
        
    return new_repo

@router.post("/{id}/enable", response_model=RepositoryResponse)
async def enable_repository_bot(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Repository:
    """Registers callback webhook on GitHub API and activates monitoring status."""
    result = await db.execute(
        select(Repository).where(Repository.id == id, Repository.user_id == current_user.id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")

    if repo.is_active and repo.webhook_id:
        return repo

    github_token = decrypt_token(current_user.github_access_token_encrypted)
    webhook_secret = decrypt_token(repo.webhook_secret_encrypted)

    try:
        # Create webhook on GitHub
        hook_id = await GitHubClient.create_webhook(
            github_token, repo.owner, repo.name, webhook_secret
        )
        
        repo.webhook_id = hook_id
        repo.is_active = True
        await db.commit()
        await db.refresh(repo)
        
        if repo.slack_webhook_url_encrypted:
            repo.slack_webhook_url = decrypt_token(repo.slack_webhook_url_encrypted)
        return repo

    except Exception as e:
        logger.error("Failed to enable repository bot: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to enable bot on GitHub: {str(e)}"
        )

@router.post("/{id}/disable", response_model=RepositoryResponse)
async def disable_repository_bot(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Repository:
    """Deletes callback webhook on GitHub API and deactivates monitoring status."""
    result = await db.execute(
        select(Repository).where(Repository.id == id, Repository.user_id == current_user.id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")

    if not repo.is_active:
        return repo

    github_token = decrypt_token(current_user.github_access_token_encrypted)

    try:
        # Remove webhook from GitHub
        if repo.webhook_id:
            await GitHubClient.delete_webhook(
                github_token, repo.owner, repo.name, repo.webhook_id
            )
        
        repo.webhook_id = None
        repo.is_active = False
        await db.commit()
        await db.refresh(repo)

        if repo.slack_webhook_url_encrypted:
            repo.slack_webhook_url = decrypt_token(repo.slack_webhook_url_encrypted)
        return repo

    except Exception as e:
        logger.error("Failed to disable repository bot: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to disable bot: {str(e)}"
        )

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_repository(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> None:
    """Disconnects a repository, removes its webhook on GitHub, and deletes it from database."""
    result = await db.execute(
        select(Repository).where(Repository.id == id, Repository.user_id == current_user.id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")

    # Try to delete webhook from GitHub if active and exists
    if repo.is_active and repo.webhook_id:
        github_token = decrypt_token(current_user.github_access_token_encrypted)
        try:
            await GitHubClient.delete_webhook(
                github_token, repo.owner, repo.name, repo.webhook_id
            )
        except Exception as e:
            logger.warning("Failed to delete webhook from GitHub during repository disconnect: %s", str(e))

    await db.delete(repo)
    await db.commit()
    return None

