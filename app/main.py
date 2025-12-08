from fastapi import FastAPI
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
import logging

from app.middlewares.timeout import TimeoutMiddleware
from app.api import endpoints
from app.config import settings


app = FastAPI(title=settings.app_name, version=settings.version, debug=settings.debug)

# Attach limiter middleware for proper request context
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

app.add_middleware(TimeoutMiddleware)  
app.add_middleware(SlowAPIMiddleware) 

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Vui lòng thử lại sau."}
    )

# Configure root logging level
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

app.include_router(endpoints.router)


