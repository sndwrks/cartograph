"""API test fixtures: the app served over ASGITransport.

The `seeded` graph fixture lives in tests/conftest.py (shared with tests/mcp).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from cartograph.api.app import create_app
from cartograph.db import get_session

@pytest.fixture
async def client(session):
    app = create_app()

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
