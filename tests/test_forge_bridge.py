"""Forge bridge routes tests — mock socket layer, auth enforcement, approval flag.

Tests the 6 forge proxy routes in aegis/web/server.py:
- POST /forge/submit -> FORGE:SUBMIT
- GET /forge/list -> FORGE:LIST
- GET /forge/{id}/status -> FORGE:POLL
- GET /forge/{id}/diff -> FORGE:FETCH
- POST /forge/{id}/gate -> FORGE:GATE with approval flag
- POST /forge/{id}/cleanup -> FORGE:CLEANUP

Mock the socket layer to verify correct FORGE command mapping and response parsing.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from aegis.web.server import app

TOKEN = "test-token-12345"
AUTH_PARAMS = {"token": TOKEN}


@pytest.fixture(autouse=True)
def mock_token():
    with patch("aegis.web.server.HELIOS_TOKEN", TOKEN):
        yield


# ---- Mock socket layer ----


class MockForgeSocket:
    """Mock socket that returns predefined responses for FORGE commands."""

    def __init__(self):
        self.responses = {
            "FORGE:SUBMIT:create a hello world function": "FORGE:OK:abc123",
            "FORGE:LIST": (
                'FORGE:LIST:[{"id": "abc123", "status": "completed"}, '
                '{"id": "def456", "status": "pending"}]'
            ),
            "FORGE:POLL:abc123": (
                'FORGE:STATUS:{"id": "abc123", "status": "completed", "spec": "hello world"}'
            ),
            "FORGE:FETCH:abc123": (
                'FORGE:RESULT:{"id": "abc123", "status": "completed", "diffs": [], "logs": "[]"}'
            ),
            "FORGE:GATE:abc123:true": (
                'FORGE:GATE:{"lint_passed": true, "test_passed": true, "build_passed": true, '
                '"owner_approved": true, "overall_passed": true}'
            ),
            "FORGE:GATE:abc123:false": (
                'FORGE:GATE:{"lint_passed": true, "test_passed": true, "build_passed": true, '
                '"owner_approved": false, "overall_passed": true}'
            ),
            "FORGE:CLEANUP:abc123": "FORGE:OK:abc123 cleaned",
        }
        self.commands_received: list[str] = []

    async def mock_command(self, cmd: str) -> str:
        """Mock response to a FORGE command."""
        self.commands_received.append(cmd)
        if cmd in self.responses:
            return self.responses[cmd]
        elif cmd.startswith("FORGE:ERR:"):
            return cmd
        else:
            return f"FORGE:ERR:unknown command {cmd}"


@pytest.fixture
def mock_forge_socket():
    mock = MockForgeSocket()
    with patch("aegis.web.server._forge_socket_command", side_effect=mock.mock_command):
        yield mock


# ---- Authentication tests ----


class TestAuth:
    def test_forge_routes_require_auth(self):
        """All forge routes must reject requests without a valid token."""
        client = TestClient(app)

        routes = [
            ("/forge/submit", "POST", {"spec": "create a hello world function"}),
            ("/forge/list", "GET", None),
            ("/forge/abc123/status", "GET", None),
            ("/forge/abc123/diff", "GET", None),
            ("/forge/abc123/gate", "POST", {"approved": True}),
            ("/forge/abc123/cleanup", "POST", None),
        ]

        for path, method, data in routes:
            if method == "POST":
                resp = client.post(path, json=data)
            else:
                resp = client.get(path)
            assert resp.status_code == 401, f"{method} {path} should require auth"
            assert resp.json() == {"detail": "auth_required"}

    def test_forge_routes_bad_token(self):
        """All forge routes must reject invalid tokens."""
        client = TestClient(app)
        bad = {"token": "bad-token"}

        resp = client.post("/forge/submit", json={"spec": "test"}, params=bad)
        assert resp.status_code == 401

        resp = client.get("/forge/list", params=bad)
        assert resp.status_code == 401

        resp = client.get("/forge/abc123/status", params=bad)
        assert resp.status_code == 401

        resp = client.get("/forge/abc123/diff", params=bad)
        assert resp.status_code == 401

        resp = client.post("/forge/abc123/gate", json={"approved": True}, params=bad)
        assert resp.status_code == 401

        resp = client.post("/forge/abc123/cleanup", params=bad)
        assert resp.status_code == 401


# ---- Submit tests ----


class TestSubmit:
    def test_submit_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.post(
            "/forge/submit",
            json={"spec": "create a hello world function"},
            params=AUTH_PARAMS,
        )
        assert resp.status_code == 200
        assert resp.json() == {"task_id": "abc123"}

    def test_submit_short_spec(self):
        client = TestClient(app)
        resp = client.post(
            "/forge/submit", json={"spec": "hi"}, params=AUTH_PARAMS
        )
        assert resp.status_code == 400
        assert "spec must be >= 10 chars" in resp.json()["detail"]

    def test_submit_no_spec(self):
        client = TestClient(app)
        resp = client.post("/forge/submit", json={}, params=AUTH_PARAMS)
        assert resp.status_code == 400
        assert "spec must be >= 10 chars" in resp.json()["detail"]

    def test_submit_invalid_json(self):
        client = TestClient(app)
        resp = client.post(
            "/forge/submit", content="not json", params=AUTH_PARAMS
        )
        assert resp.status_code == 400
        assert "invalid JSON body" in resp.json()["detail"]

    def test_submit_forge_error(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:forge not initialized"

        with patch("aegis.web.server._forge_socket_command", side_effect=err_cmd):
            resp = client.post(
                "/forge/submit",
                json={"spec": "create a hello world function"},
                params=AUTH_PARAMS,
            )
            assert resp.status_code == 400
            assert "forge not initialized" in resp.json()["detail"]


# ---- List tests ----


class TestList:
    def test_list_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.get("/forge/list", params=AUTH_PARAMS)
        assert resp.status_code == 200
        tasks = resp.json()
        assert len(tasks) == 2
        assert tasks[0]["id"] == "abc123"
        assert tasks[0]["status"] == "completed"
        assert tasks[1]["id"] == "def456"
        assert tasks[1]["status"] == "pending"

    def test_list_forge_error(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:forge not initialized"

        with patch("aegis.web.server._forge_socket_command", side_effect=err_cmd):
            resp = client.get("/forge/list", params=AUTH_PARAMS)
            assert resp.status_code == 400
            assert "forge not initialized" in resp.json()["detail"]

    def test_list_invalid_json(self):
        client = TestClient(app)

        async def bad_json(cmd):
            return "FORGE:LIST:not json"

        with patch("aegis.web.server._forge_socket_command", side_effect=bad_json):
            resp = client.get("/forge/list", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "invalid task list JSON" in resp.json()["detail"]


# ---- Status tests ----


class TestStatus:
    def test_get_status_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.get("/forge/abc123/status", params=AUTH_PARAMS)
        assert resp.status_code == 200
        task = resp.json()
        assert task["id"] == "abc123"
        assert task["status"] == "completed"
        assert task["spec"] == "hello world"

    def test_get_status_unknown_task(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:unknown task xyz999"

        with patch("aegis.web.server._forge_socket_command", side_effect=err_cmd):
            resp = client.get("/forge/xyz999/status", params=AUTH_PARAMS)
            assert resp.status_code == 404
            assert "unknown task" in resp.json()["detail"]

    def test_get_status_invalid_json(self):
        client = TestClient(app)

        async def bad_json(cmd):
            return "FORGE:STATUS:not json"

        with patch("aegis.web.server._forge_socket_command", side_effect=bad_json):
            resp = client.get("/forge/abc123/status", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "invalid task JSON" in resp.json()["detail"]


# ---- Diff tests ----


class TestDiff:
    def test_get_diff_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.get("/forge/abc123/diff", params=AUTH_PARAMS)
        assert resp.status_code == 200
        result = resp.json()
        assert result["id"] == "abc123"
        assert result["status"] == "completed"
        assert result["diffs"] == []
        assert result["logs"] == "[]"

    def test_get_diff_unknown_task(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:unknown task xyz999"

        with patch("aegis.web.server._forge_socket_command", side_effect=err_cmd):
            resp = client.get("/forge/xyz999/diff", params=AUTH_PARAMS)
            assert resp.status_code == 404
            assert "unknown task" in resp.json()["detail"]

    def test_get_diff_invalid_json(self):
        client = TestClient(app)

        async def bad_json(cmd):
            return "FORGE:RESULT:not json"

        with patch("aegis.web.server._forge_socket_command", side_effect=bad_json):
            resp = client.get("/forge/abc123/diff", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "invalid result JSON" in resp.json()["detail"]


# ---- Gate tests ----


class TestGate:
    def test_gate_approve_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.post(
            "/forge/abc123/gate",
            json={"approved": True},
            params=AUTH_PARAMS,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["lint_passed"] is True
        assert result["test_passed"] is True
        assert result["build_passed"] is True
        assert result["owner_approved"] is True
        assert result["overall_passed"] is True

    def test_gate_reject_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.post(
            "/forge/abc123/gate",
            json={"approved": False},
            params=AUTH_PARAMS,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["owner_approved"] is False
        assert result["overall_passed"] is True

    def test_gate_missing_approved_defaults_false(self, mock_forge_socket):
        """When approved field is missing, defaults to False (reject)."""
        client = TestClient(app)
        resp = client.post(
            "/forge/abc123/gate", json={}, params=AUTH_PARAMS
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["owner_approved"] is False

    def test_gate_invalid_approved_type(self):
        client = TestClient(app)
        resp = client.post(
            "/forge/abc123/gate",
            json={"approved": "yes"},
            params=AUTH_PARAMS,
        )
        assert resp.status_code == 400
        assert "approved must be boolean" in resp.json()["detail"]

    def test_gate_forge_error(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:task not completed (status=pending)"

        with patch("aegis.web.server._forge_socket_command", side_effect=err_cmd):
            resp = client.post(
                "/forge/abc123/gate",
                json={"approved": True},
                params=AUTH_PARAMS,
            )
            assert resp.status_code == 400
            assert "task not completed" in resp.json()["detail"]

    def test_gate_sends_correct_command(self, mock_forge_socket):
        """Verify gate sends FORGE:GATE:<id>:<true|false>."""
        client = TestClient(app)
        client.post(
            "/forge/abc123/gate",
            json={"approved": True},
            params=AUTH_PARAMS,
        )
        assert "FORGE:GATE:abc123:true" in mock_forge_socket.commands_received

        client.post(
            "/forge/abc123/gate",
            json={"approved": False},
            params=AUTH_PARAMS,
        )
        assert "FORGE:GATE:abc123:false" in mock_forge_socket.commands_received


# ---- Cleanup tests ----


class TestCleanup:
    def test_cleanup_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.post("/forge/abc123/cleanup", params=AUTH_PARAMS)
        assert resp.status_code == 200
        assert resp.json() == {"message": "abc123 cleaned"}

    def test_cleanup_unknown_task(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:unknown task xyz999"

        with patch("aegis.web.server._forge_socket_command", side_effect=err_cmd):
            resp = client.post("/forge/xyz999/cleanup", params=AUTH_PARAMS)
            assert resp.status_code == 400
            assert "unknown task" in resp.json()["detail"]


# ---- Error handling tests ----


class TestErrorHandling:
    def test_socket_connection_error(self):
        """Simulates the HTTPException that _forge_socket_command raises on OSError."""
        from fastapi import HTTPException

        async def conn_err(cmd):
            raise HTTPException(status_code=503, detail="socket_unavailable: Connection refused")

        client = TestClient(app)
        with patch("aegis.web.server._forge_socket_command", side_effect=conn_err):
            resp = client.post(
                "/forge/submit",
                json={"spec": "create a hello world function"},
                params=AUTH_PARAMS,
            )
            assert resp.status_code == 503
            assert "socket_unavailable" in resp.json()["detail"]

    def test_unexpected_response(self):
        client = TestClient(app)

        async def bad_resp(cmd):
            return "SOME:UNEXPECTED:RESPONSE"

        with patch("aegis.web.server._forge_socket_command", side_effect=bad_resp):
            resp = client.post(
                "/forge/submit",
                json={"spec": "create a hello world function"},
                params=AUTH_PARAMS,
            )
            assert resp.status_code == 502
            assert "unexpected response" in resp.json()["detail"]


# ---- FORGE command mapping tests ----


class TestCommandMapping:
    def test_submit_maps_to_forge_submit(self, mock_forge_socket):
        client = TestClient(app)
        client.post(
            "/forge/submit",
            json={"spec": "create a hello world function"},
            params=AUTH_PARAMS,
        )
        assert "FORGE:SUBMIT:create a hello world function" in mock_forge_socket.commands_received

    def test_list_maps_to_forge_list(self, mock_forge_socket):
        client = TestClient(app)
        client.get("/forge/list", params=AUTH_PARAMS)
        assert "FORGE:LIST" in mock_forge_socket.commands_received

    def test_status_maps_to_forge_poll(self, mock_forge_socket):
        client = TestClient(app)
        client.get("/forge/abc123/status", params=AUTH_PARAMS)
        assert "FORGE:POLL:abc123" in mock_forge_socket.commands_received

    def test_diff_maps_to_forge_fetch(self, mock_forge_socket):
        client = TestClient(app)
        client.get("/forge/abc123/diff", params=AUTH_PARAMS)
        assert "FORGE:FETCH:abc123" in mock_forge_socket.commands_received

    def test_gate_maps_to_forge_gate(self, mock_forge_socket):
        client = TestClient(app)
        client.post(
            "/forge/abc123/gate",
            json={"approved": True},
            params=AUTH_PARAMS,
        )
        assert "FORGE:GATE:abc123:true" in mock_forge_socket.commands_received

    def test_cleanup_maps_to_forge_cleanup(self, mock_forge_socket):
        client = TestClient(app)
        client.post("/forge/abc123/cleanup", params=AUTH_PARAMS)
        assert "FORGE:CLEANUP:abc123" in mock_forge_socket.commands_received
