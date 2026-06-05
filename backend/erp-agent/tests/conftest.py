import pytest


@pytest.fixture(autouse=True)
def _reset_mcp_client():
    yield
    import app.mcp.client as mc
    mc._client = None
    from app.agent import mcp_client
    mcp_client._tools = None
    mcp_client._client = None
