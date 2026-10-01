import logging
import sys
import types
from pathlib import Path

# Resolve absolute backend package imports when running locally or on Vercel (/var/task)
_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root.parent) not in sys.path:
    sys.path.insert(0, str(_backend_root.parent))
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

if "backend" not in sys.modules:
    _backend_pkg = types.ModuleType("backend")
    _backend_pkg.__path__ = [str(_backend_root)]
    sys.modules["backend"] = _backend_pkg

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
from starlette.exceptions import HTTPException as StarletteHTTPException
from backend.app.core.config import settings
from backend.app.core.logging import setup_logging
from backend.app.middleware.logging_middleware import LoggingMiddleware
from backend.app.api.v1.router import api_router
from backend.app.models.base import Base
import backend.app.models  # Ensure all model tables registered
from backend.app.db.session import engine
from backend.app.services.queue import event_queue

# Initialize structured logging configuration
setup_logging()
logger = logging.getLogger("app.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database schema automatically for zero-config local runs
    if "sqlite" in settings.DATABASE_URL and not settings.TESTING:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema verified for %s", settings.DATABASE_URL)
        except Exception as e:
            logger.warning("Could not auto-create tables: %s", e)

    # Launch background distributed queue worker (disabled in serverless Vercel function)
    if not settings.VERCEL:
        await event_queue.start_worker()
    yield
    # Graceful shutdown of queue worker
    if not settings.VERCEL:
        await event_queue.stop_worker()

# Instantiate FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Production-ready async FastAPI backend for Darkrai - Event-Driven GitHub Automation Platform.",
    version="1.0.0",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Apply CORS (Cross-Origin Resource Sharing) middleware
# Configured via BACKEND_CORS_ORIGINS from env/config settings
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Attach request-response performance and trace logging middleware
app.add_middleware(LoggingMiddleware)

# Include v1 routes under '/api/v1' path prefix
app.include_router(api_router, prefix="/api/v1")

@app.get("/")
@app.head("/")
async def root() -> JSONResponse:
    """Root endpoint welcoming requests and confirming service availability."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "online",
            "app": settings.APP_NAME,
            "docs_url": "/docs",
            "health_check": "/api/v1/health"
        }
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Interceptors custom exception responses for HTTP exceptions."""
    logger.warning("HTTP error occurred: %s %s - Status %s: %s", 
                   request.method, request.url.path, exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Interceptors validation error responses and structures parameter errors."""
    logger.warning("Request validation failed: %s %s - Errors: %s", 
                   request.method, request.url.path, exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": exc.errors()
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback catch-all handler for unhandled runtime exceptions."""
    logger.error("Unhandled runtime exception: %s %s - Error: %s", 
                 request.method, request.url.path, str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error occurred."},
    )
