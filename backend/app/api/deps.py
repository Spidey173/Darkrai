from collections.abc import AsyncGenerator
from uuid import UUID
from fastapi import Request, WebSocket, HTTPException, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db.session import get_async_session, async_session_maker
from backend.app.models.user import User
from backend.app.utils.jwt import decode_session_token
from backend.app.core.config import settings

# Expose session generator for FastAPI path dependency injection
get_db = get_async_session

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency validating the session JWT from cookie, Authorization header, or query param, and fetching the active User."""
    cookie_token = request.cookies.get("session_token")
    auth_header = request.headers.get("Authorization")
    is_bearer = bool(auth_header and auth_header.startswith("Bearer "))

    if cookie_token and not is_bearer and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        # CSRF Protection: Protect cookie-authenticated state-changing requests against CSRF
        csrf_header = request.headers.get("x-requested-with") or request.headers.get("x-csrf-token")
        sec_fetch_site = request.headers.get("sec-fetch-site")
        origin = request.headers.get("origin")

        is_safe = False
        if sec_fetch_site in ("same-origin", "same-site"):
            is_safe = True
        elif csrf_header:
            is_safe = True
        elif origin:
            is_safe = any(origin.startswith(str(o).rstrip("/")) for o in settings.BACKEND_CORS_ORIGINS)

        if not is_safe:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed: Cookie-authenticated state-changing request requires X-Requested-With, X-CSRF-Token, or verified origin."
            )

    session_token = cookie_token
    if not session_token:
        if is_bearer:
            session_token = auth_header[7:].strip()
    if not session_token:
        session_token = request.query_params.get("token")

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

    try:
        parsed_user_id = UUID(str(user_id))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token invalid: malformed user identifier."
        )
        
    result = await db.execute(select(User).where(User.id == parsed_user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User session valid, but record not found."
        )
    return user

async def get_current_user_ws(
    websocket: WebSocket,
) -> User:
    """Authenticates a WebSocket connection using cookie or token query parameter."""
    session_token = websocket.cookies.get("session_token")
    if not session_token:
        session_token = websocket.query_params.get("token")
        
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

    try:
        parsed_user_id = UUID(str(user_id))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token invalid: malformed user identifier."
        )
        
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.id == parsed_user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found."
            )
        return user

