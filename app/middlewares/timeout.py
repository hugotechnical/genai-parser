import asyncio
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.utils.logger import setup_logger

from app.config import settings

logger = setup_logger(__name__)

API_TIMEOUT = settings.timeout or 300

class TimeoutMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response_future = asyncio.Future()
        
        async def process_request():
            try:
                response = await call_next(request)
                if not response_future.done():
                    response_future.set_result(response)
            except Exception as e:
                if not response_future.done():
                    response_future.set_exception(e)
        
        task = asyncio.create_task(process_request())
        
        try:
            response = await asyncio.wait_for(response_future, timeout=API_TIMEOUT)
            return response
        except asyncio.TimeoutError:
            logger.error(f"⏱️ Request timeout sau {API_TIMEOUT} giây: {request.url.path}")
            return JSONResponse(
                status_code=504,
                content={"detail": f"Xử lý request vượt quá thời gian cho phép ({API_TIMEOUT} giây)"}
            )