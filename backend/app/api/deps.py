from collections.abc import AsyncGenerator
from fastapi import Request, HTTPException, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db.session import get_async_session
from backend.app.models.user import User
from backend.app.utils.jwt import decode_session_token

# Expose session generator for FastAPI path dependency injection
get_db = get_async_session

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency validating the session cookie JWT and fetching the active User from Postgres."""
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Session token missing."
        )
    
    user_id = decode_session_token(session_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token invalid or expired."
        )
        
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User session valid, but record not found."
        )
        
    return user
