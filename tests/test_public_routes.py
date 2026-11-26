"""Check the public application boundary without accessing storage or a database."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize("method,path", [
    ("GET", "/professor/users"),
    ("PATCH", "/professor/users/example/role"),
    ("GET", "/api/v1/build/objdump"),
])
def test_retired_routes_are_unavailable(method, path):
    client = TestClient(app)
    assert client.request(method, path).status_code == 404
    paths = app.openapi()["paths"]
    assert "/professor/users" not in paths
    assert "/professor/users/{user_id}/role" not in paths
    assert "/api/v1/build/objdump" not in paths


def test_compile_logs_simulation_and_diagnostics_remain_registered():
    paths = app.openapi()["paths"]
    for method, path in [
        ("post", "/api/v1/build/compile"),
        ("get", "/api/v1/build/logs"),
        ("post", "/api/v1/simulation/run"),
        ("post", "/api/v1/tutor/sample"),
        ("get", "/api/v1/assistant/status"),
        ("get", "/api/v1/assistant/transport-check"),
        ("post", "/api/v1/assistant/chat"),
        ("get", "/"),
    ]:
        assert method in paths[path]
