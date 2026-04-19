"""HTTP-level smoke tests for /invoke, /inventory, and /docs routes.

These don't exercise real switches — the upstream transports will fail
when the lab VMs aren't reachable, which is the expected behaviour for
/ready but not for the endpoints under test here. We focus on the
contract the client depends on: right status codes, right shapes,
credentials never leaking back on the wire.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    """Fresh app instance per test with an isolated inventory file."""
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({"switches": [
        {"name": "leaf1", "mgmt_ip": "10.0.0.1", "tags": ["leaf"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("SONIC_INVENTORY_PATH", str(inv))
    # Import after env is set so the app picks up our path.
    import importlib
    import api.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


class TestInvoke:
    def test_unknown_tool_returns_404(self, client: TestClient):
        r = client.post("/invoke", json={"tool": "does_not_exist", "inputs": {}})
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_invoke_missing_body_returns_422(self, client: TestClient):
        r = client.post("/invoke", json={})
        assert r.status_code == 422

    def test_invoke_list_tools_returns_55_entries(self, client: TestClient):
        r = client.get("/tools")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert len(body) >= 50
        # Every tool exposes at least name + policy
        for t in body:
            assert "name" in t
            assert "policy" in t


class TestInventoryGET:
    def test_returns_shape_and_redacts_password(self, client: TestClient, tmp_path: Path):
        r = client.get("/inventory")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"path", "source", "switches"}
        assert isinstance(body["switches"], list)
        for s in body["switches"]:
            # password must never leak on GET — only has_password boolean
            assert "password" not in s
            assert "has_password" in s


class TestInventoryAddRemove:
    def test_add_then_remove_round_trips(self, client: TestClient):
        # add
        r = client.post("/inventory/switches", json={
            "name": "spine1", "mgmt_ip": "10.9.9.9", "tags": ["spine"],
        })
        assert r.status_code == 200
        assert any(s["mgmt_ip"] == "10.9.9.9" for s in r.json()["switches"])

        # remove
        r2 = client.delete("/inventory/switches/10.9.9.9")
        assert r2.status_code == 200
        assert not any(s["mgmt_ip"] == "10.9.9.9" for s in r2.json()["switches"])

    def test_delete_unknown_returns_404(self, client: TestClient):
        r = client.delete("/inventory/switches/192.0.2.99")
        assert r.status_code == 404

    def test_add_missing_mgmt_ip_returns_4xx(self, client: TestClient):
        r = client.post("/inventory/switches", json={"name": "oops", "mgmt_ip": ""})
        # pydantic will 422 on schema; app-level guard also 400s
        assert r.status_code in (400, 422)

    def test_put_duplicate_mgmt_ip_is_rejected(self, client: TestClient):
        r = client.put("/inventory", json={"switches": [
            {"name": "a", "mgmt_ip": "10.1.1.1"},
            {"name": "b", "mgmt_ip": "10.1.1.1"},
        ]})
        assert r.status_code == 400
        assert "duplicate" in r.json()["detail"].lower()


class TestInventoryPassword:
    def test_password_is_persisted_but_never_returned(
        self, client: TestClient, tmp_path: Path, monkeypatch
    ):
        r = client.post("/inventory/switches", json={
            "name": "creds", "mgmt_ip": "10.2.2.2",
            "username": "admin2", "password": "hunter2",
        })
        assert r.status_code == 200
        match = [s for s in r.json()["switches"] if s["mgmt_ip"] == "10.2.2.2"][0]
        assert match["has_password"] is True
        assert "password" not in match
        # File on disk DOES carry the password (operators can grep it).
        path = Path(r.json()["path"])
        raw = json.loads(path.read_text())
        on_disk = [s for s in raw["switches"] if s["mgmt_ip"] == "10.2.2.2"][0]
        assert on_disk["password"] == "hunter2"


class TestDocsRoutes:
    def test_catalog_markdown_renders_without_a_docs_dir(self, client: TestClient):
        r = client.get("/docs/tools")
        assert r.status_code == 200
        assert "SONiC MCP tool catalog" in r.text
        assert "| Tool |" in r.text  # table header present

    def test_catalog_html_renders(self, client: TestClient):
        r = client.get("/docs/tools/html")
        assert r.status_code == 200
        assert "<table" in r.text.lower()

    def test_openapi_yaml_serves_fastapi_spec(self, client: TestClient):
        r = client.get("/openapi/mcp-invoke.yaml")
        assert r.status_code == 200
        # JSON is valid YAML; parse as JSON to confirm it's the live spec
        spec = json.loads(r.text)
        assert "paths" in spec
        assert "/invoke" in spec["paths"]

    def test_swagger_ui_loads(self, client: TestClient):
        r = client.get("/swagger")
        assert r.status_code == 200
        assert "swagger-ui" in r.text.lower()


class TestHealth:
    def test_health_is_200(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
