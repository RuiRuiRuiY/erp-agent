from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.database import init_db
from app.core.exceptions import register_exception_handlers
from app.dashboard.views import setup_admin


@asynccontextmanager
async def lifespan(_application: FastAPI):
    init_db()
    yield


app = FastAPI(title="Mock ERP API", lifespan=lifespan)

app.include_router(api_router, prefix="/api/v1")
register_exception_handlers(app)
setup_admin(app)
