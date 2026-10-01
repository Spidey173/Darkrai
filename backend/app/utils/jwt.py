from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict
import logging
from jose import jwt, JWTError
from backend.app.core.config import settings

logger = logging.getLogger("app.utils.jwt")

ALGORITHM = "HS256"

def create_session_token(user_id: str, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a secure JWT token containing the user ID subject."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=7) # Default session 7 days
        
    to_encode = {
        "sub": user_id,
        "exp": int(expire.timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp())
    }
    
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)

def decode_session_token(token: str) -> Optional[str]:
    """Decodes a JWT session token and returns the user ID subject if valid."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            return None
        return user_id
    except JWTError as e:
        logger.debug("JWT decoding validation failed: %s", str(e))
        return None
