import pytest


@pytest.fixture(autouse=True)
def _reset_mcp_client():
    yield
    import app.mcp.erp_client as ec
    ec._client = None
    import app.mcp.client as mc
    mc._tools = None
    mc._client = None
