import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import AsyncGenerator

# Add project root directory to path to resolve backend imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import pytest
import httpx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Configure test environment variables BEFORE importing app models/settings
test_db_path = os.path.join(tempfile.gettempdir(), "darkrai_test.db")
if os.path.exists(test_db_path):
    try:
        os.remove(test_db_path)
    except Exception:
        pass

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{test_db_path}"
os.environ["APP_ENV"] = "testing"

from backend.app.main import app
from backend.app.api.deps import get_db
from backend.app.core.config import settings
from backend.app.models import Base
import backend.app.db.session as db_session_module

# Point settings and global session maker to test database
settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db_path}"
test_engine = create_async_engine(settings.DATABASE_URL, echo=False)
test_session_maker = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)
db_session_module.engine = test_engine
db_session_module.async_session_maker = test_session_maker

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def _init_tables():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            
    loop.run_until_complete(_init_tables())
    yield
    
    async def _cleanup():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await test_engine.dispose()
        
    loop.run_until_complete(_cleanup())
    loop.close()
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass

@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_maker() as session:
        yield session

@pytest.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _get_test_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_test_db
    
    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
        
    app.dependency_overrides.clear()
