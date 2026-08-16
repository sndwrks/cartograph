import pytest
from httpx import ASGITransport, AsyncClient

from codegraph.mcp_server.auth import BearerAuthMiddleware

TOKEN = "test-token"


async def ok_app(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain"), (b"content-length", b"2")],
        }
    )
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.fixture
async def client():
    app = BearerAuthMiddleware(ok_app, TOKEN)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_missing_header_401(client):
    r = await client.post("/mcp")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_wrong_token_401(client):
    r = await client.post("/mcp", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_wrong_scheme_401(client):
    r = await client.post("/mcp", headers={"Authorization": TOKEN})
    assert r.status_code == 401


async def test_right_token_passes(client):
    r = await client.post("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.text == "ok"


async def test_healthz_open(client):
    assert (await client.get("/healthz")).status_code == 200


def test_empty_token_refuses_to_start():
    with pytest.raises(RuntimeError, match="MCP_BEARER_TOKEN"):
        BearerAuthMiddleware(ok_app, "")
