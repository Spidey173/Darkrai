import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text
from backend.app.api.deps import get_db

logger = logging.getLogger("app.api.v1.health")
router = APIRouter()

@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check(db: AsyncSession = Depends(get_db)) -> dict:
    """Diagnostic health check verifying API server responsiveness and database connection health."""
    try:
        # Asynchronously verify database connection is responsive
        await db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "database": "connected",
        }
    except Exception as e:
        logger.error("Health check database check failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failure",
        )
