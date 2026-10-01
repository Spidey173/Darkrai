import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.api.deps import get_db, get_current_user
from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.schemas.user import UserResponse
from backend.app.services.encryption import encrypt_token
from backend.app.services.github_auth import GitHubAuthService
from backend.app.utils.jwt import create_session_token

logger = logging.getLogger("app.api.v1.auth")
router = APIRouter()

STATE_COOKIE_NAME = "oauth_state"
SESSION_COOKIE_NAME = "session_token"
STATE_EXPIRY_SECONDS = 600  # 10 minutes

@router.get("/github/login")
async def github_login() -> RedirectResponse:
    """Redirects the client browser to GitHub's OAuth authorization page."""
    state = secrets.token_urlsafe(32)
    
    scopes = "repo read:user user:email"
    github_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.GITHUB_CLIENT_ID}"
        f"&scope={scopes}"
        f"&state={state}"
    )
    
    redirect_response = RedirectResponse(url=github_url)
    
    # Securely store state in a short-lived HTTP-only cookie to prevent CSRF
    is_dev = settings.APP_ENV == "development"
    redirect_response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        secure=not is_dev,
        samesite="lax",
        max_age=STATE_EXPIRY_SECONDS,
        path="/"  # Restrict scope of cookie globally
    )
    
    # Prevent proxy caching of authorization redirect response on Vercel/CDNs
    redirect_response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    redirect_response.headers["Pragma"] = "no-cache"
    redirect_response.headers["Expires"] = "0"
    
    return redirect_response


@router.get("/github/callback")
async def github_callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    """GitHub OAuth callback handling state validation, token exchange, and user upsert."""
    # 1. Handle GitHub returned errors
    if error:
        logger.error("GitHub callback returned error: %s", error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub OAuth error: {error}"
        )

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameters."
        )

    # 2. Verify state token matching
    cookie_state = request.cookies.get(STATE_COOKIE_NAME)
    if not cookie_state or cookie_state != state:
        logger.warning("OAuth state verification failed. Match: %s", cookie_state == state)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state validation failed. Potential CSRF detected."
        )

    # 3. Exchange code for access tokens
    token_data = await GitHubAuthService.exchange_code_for_token(code)
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token response did not include access token."
        )

    # 4. Fetch user details
    profile = await GitHubAuthService.get_user_profile(access_token)
    github_id = profile.get("id")
    github_username = profile.get("login")
    
    if not github_id or not github_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to retrieve complete user metadata from GitHub."
        )

    primary_email = await GitHubAuthService.get_primary_email(access_token, profile)
    avatar_url = profile.get("avatar_url")

    # 5. Encrypt access/refresh tokens
    encrypted_access_token = encrypt_token(access_token)
    encrypted_refresh_token = None
    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        encrypted_refresh_token = encrypt_token(refresh_token)

    expires_in = token_data.get("expires_in")
    token_expires_at = None
    if expires_in:
        token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    # 6. Upsert user in database
    result = await db.execute(select(User).where(User.github_user_id == github_id))
    user = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if not user:
        # Create User
        user = User(
            github_user_id=github_id,
            github_username=github_username,
            email=primary_email,
            avatar_url=avatar_url,
            github_access_token_encrypted=encrypted_access_token,
            github_refresh_token_encrypted=encrypted_refresh_token,
            token_expires_at=token_expires_at,
            last_login_at=now,
        )
        db.add(user)
    else:
        # Update existing records
        user.github_username = github_username
        user.email = primary_email
        user.avatar_url = avatar_url
        user.github_access_token_encrypted = encrypted_access_token
        user.github_refresh_token_encrypted = encrypted_refresh_token
        user.token_expires_at = token_expires_at
        user.last_login_at = now

    await db.commit()
    await db.refresh(user)

    # 7. Create Session token and configure secure session cookie
    session_token = create_session_token(str(user.id))
    
    is_dev = settings.APP_ENV == "development"
    
    # Create redirection target to frontend
    redirect_target = "/dashboard"
    if settings.BACKEND_CORS_ORIGINS:
        redirect_target = f"{settings.BACKEND_CORS_ORIGINS[0]}/dashboard"

    redirect_response = RedirectResponse(url=redirect_target)
    
    # Delete temporary state cookie
    redirect_response.delete_cookie(key=STATE_COOKIE_NAME, path="/")
    
    # Establish HttpOnly Session cookie
    redirect_response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=not is_dev,
        samesite="lax",
        max_age=7 * 24 * 3600,  # 7 days
        path="/"
    )

    # Prevent proxy caching of callback redirect response
    redirect_response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    redirect_response.headers["Pragma"] = "no-cache"
    redirect_response.headers["Expires"] = "0"

    return redirect_response


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(response: Response) -> dict:
    """Invalidates the active user session cookie."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/"
    )
    return {"detail": "Logged out successfully"}

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    """Returns the authenticated profile session details."""
    return current_user
