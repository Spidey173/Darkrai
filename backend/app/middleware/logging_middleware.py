import logging
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("app.middleware.logging")

class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log request details, execution duration, and response status."""
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.perf_counter()
        method = request.method
        path = request.url.path
        
        logger.debug("Request started: %s %s", method, path)
        
        try:
            response = await call_next(request)
            duration = time.perf_counter() - start_time
            
            logger.info(
                "Request completed: %s %s - Status: %s - Duration: %.4fs",
                method,
                path,
                response.status_code,
                duration
            )
            return response
            
        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(
                "Request failed: %s %s - Exception: %s - Duration: %.4fs",
                method,
                path,
                str(e),
                duration,
                exc_info=True
            )
            raise
        
