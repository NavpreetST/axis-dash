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

import json

import pytest
from unittest.mock import MagicMock, patch
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
                '"owner_approved": false, "overall_passed": false}'
            ),
            "FORGE:CLEANUP:abc123": "FORGE:OK:abc123 cleaned",
        }
        self.commands_received: list[str] = []

    async def mock_command(self, cmd: str) -> str:
        """Mock response to a FORGE command."""
        self.commands_received.append(cmd)
        if cmd in self.responses:
            return self.responses[cmd]
        else:
            return f"FORGE:ERR:unknown command {cmd}"


@pytest.fixture
def mock_forge_socket():
    mock = MockForgeSocket()
    with patch("aegis.web.server._forge_socket_cmd", side_effect=mock.mock_command):
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
            ("/forge/abc123/gate", "POST", {"approve": True}),
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

        resp = client.post("/forge/abc123/gate", json={"approve": True}, params=bad)
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
        assert resp.json()["detail"] == "invalid_spec"

    def test_submit_no_spec(self):
        client = TestClient(app)
        resp = client.post("/forge/submit", json={}, params=AUTH_PARAMS)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid_spec"

    def test_submit_non_dict_body(self):
        """Array body is valid JSON but not a dict → handled gracefully."""
        client = TestClient(app)
        resp = client.post(
            "/forge/submit", json=["spec"], params=AUTH_PARAMS
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid_spec"

    def test_submit_forge_error(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:forge not initialized"

        with patch("aegis.web.server._forge_socket_cmd", side_effect=err_cmd):
            resp = client.post(
                "/forge/submit",
                json={"spec": "create a hello world function"},
                params=AUTH_PARAMS,
            )
            assert resp.status_code == 502
            assert "forge not initialized" in resp.json()["detail"]


# ---- List tests ----


class TestList:
    def test_list_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.get("/forge/list", params=AUTH_PARAMS)
        assert resp.status_code == 200
        body = resp.json()
        assert "tasks" in body
        tasks = body["tasks"]
        assert len(tasks) == 2
        assert tasks[0]["id"] == "abc123"
        assert tasks[0]["status"] == "completed"
        assert tasks[1]["id"] == "def456"
        assert tasks[1]["status"] == "pending"

    def test_list_forge_error(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:forge not initialized"

        with patch("aegis.web.server._forge_socket_cmd", side_effect=err_cmd):
            resp = client.get("/forge/list", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "forge not initialized" in resp.json()["detail"]

    def test_list_invalid_json(self):
        client = TestClient(app)

        async def bad_json(cmd):
            return "FORGE:LIST:not json"

        with patch("aegis.web.server._forge_socket_cmd", side_effect=bad_json):
            resp = client.get("/forge/list", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "malformed_response" in resp.json()["detail"]


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

        with patch("aegis.web.server._forge_socket_cmd", side_effect=err_cmd):
            resp = client.get("/forge/xyz999/status", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "unknown task" in resp.json()["detail"]

    def test_get_status_invalid_json(self):
        client = TestClient(app)

        async def bad_json(cmd):
            return "FORGE:STATUS:not json"

        with patch("aegis.web.server._forge_socket_cmd", side_effect=bad_json):
            resp = client.get("/forge/abc123/status", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "malformed_response" in resp.json()["detail"]


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

        with patch("aegis.web.server._forge_socket_cmd", side_effect=err_cmd):
            resp = client.get("/forge/xyz999/diff", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "unknown task" in resp.json()["detail"]

    def test_get_diff_invalid_json(self):
        client = TestClient(app)

        async def bad_json(cmd):
            return "FORGE:RESULT:not json"

        with patch("aegis.web.server._forge_socket_cmd", side_effect=bad_json):
            resp = client.get("/forge/abc123/diff", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "malformed_response" in resp.json()["detail"]


# ---- Gate tests ----


class TestGate:
    def test_gate_approve_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.post(
            "/forge/abc123/gate",
            json={"approve": True},
            params=AUTH_PARAMS,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["lint_passed"] is True
        assert result["test_passed"] is True
        assert result["build_passed"] is True
        assert result["owner_approved"] is True
        assert result["overall_passed"] is True

    def test_gate_reject_not_bool(self):
        """Gate requires approve to be a bool; non-bool values are 400."""
        client = TestClient(app)
        for body in [{}, {"approve": "yes"}, {"approve": 1}, {"approve": None}]:
            resp = client.post(
                "/forge/abc123/gate", json=body, params=AUTH_PARAMS
            )
            assert resp.status_code == 400
            assert resp.json()["detail"] == "approval_required"

    def test_gate_reject_explicit(self, mock_forge_socket):
        """Explicit approve=False passes flag through and returns owner_approved=false."""
        client = TestClient(app)
        resp = client.post(
            "/forge/abc123/gate",
            json={"approve": False},
            params=AUTH_PARAMS,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["owner_approved"] is False
        assert result["overall_passed"] is False
        assert "FORGE:GATE:abc123:false" in mock_forge_socket.commands_received

    def test_gate_forge_error(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:task not completed (status=pending)"

        with patch("aegis.web.server._forge_socket_cmd", side_effect=err_cmd):
            resp = client.post(
                "/forge/abc123/gate",
                json={"approve": True},
                params=AUTH_PARAMS,
            )
            assert resp.status_code == 502
            assert "task not completed" in resp.json()["detail"]

    def test_gate_sends_correct_command(self, mock_forge_socket):
        """Active gate sends FORGE:GATE:<id>:true."""
        client = TestClient(app)
        client.post(
            "/forge/abc123/gate",
            json={"approve": True},
            params=AUTH_PARAMS,
        )
        assert "FORGE:GATE:abc123:true" in mock_forge_socket.commands_received


# ---- Cleanup tests ----


class TestCleanup:
    def test_cleanup_success(self, mock_forge_socket):
        client = TestClient(app)
        resp = client.post("/forge/abc123/cleanup", params=AUTH_PARAMS)
        assert resp.status_code == 200
        assert resp.json() == {"result": "FORGE:OK:abc123 cleaned"}

    def test_cleanup_unknown_task(self):
        client = TestClient(app)

        async def err_cmd(cmd):
            return "FORGE:ERR:unknown task xyz999"

        with patch("aegis.web.server._forge_socket_cmd", side_effect=err_cmd):
            resp = client.post("/forge/xyz999/cleanup", params=AUTH_PARAMS)
            assert resp.status_code == 502
            assert "unknown task" in resp.json()["detail"]


# ---- Error handling tests ----


class TestErrorHandling:
    def test_socket_connection_error(self):
        """Simulates the HTTPException that _forge_socket_cmd raises on OSError."""
        from fastapi import HTTPException

        async def conn_err(cmd):
            raise HTTPException(status_code=503, detail="socket_unavailable: Connection refused")

        client = TestClient(app)
        with patch("aegis.web.server._forge_socket_cmd", side_effect=conn_err):
            resp = client.post(
                "/forge/submit",
                json={"spec": "create a hello world function"},
                params=AUTH_PARAMS,
            )
            assert resp.status_code == 503
            assert "socket_unavailable" in resp.json()["detail"]

    def test_unexpected_response(self):
        """Active routes echo the raw response as the 502 detail."""
        client = TestClient(app)

        async def bad_resp(cmd):
            return "SOME:UNEXPECTED:RESPONSE"

        with patch("aegis.web.server._forge_socket_cmd", side_effect=bad_resp):
            resp = client.post(
                "/forge/submit",
                json={"spec": "create a hello world function"},
                params=AUTH_PARAMS,
            )
            assert resp.status_code == 502
            assert "SOME:UNEXPECTED:RESPONSE" in resp.json()["detail"]


# ---- Large response buffer limit tests ----


class TestLargeResponse:
    """Verify _forge_socket_cmd handles responses >64KB (default StreamReader limit)."""

    @pytest.mark.asyncio
    async def test_large_forge_list_response_reads_full(self):
        """FORGE:LIST response >64KB must be readable without ValueError after limit increase."""
        import asyncio
        from unittest.mock import AsyncMock
        from aegis.web.server import _forge_socket_cmd

        # Build a ~70KB task list payload
        tasks = [
            {"id": f"task{i:04d}", "status": "completed", "spec": "x" * 500}
            for i in range(120)
        ]
        payload = json.dumps(tasks)
        assert len(payload) > 65536, f"payload {len(payload)} bytes < 64KB for realistic test"

        response = f"FORGE:LIST:{payload}\n"
        response_bytes = response.encode()

        # Mock open_unix_connection to return a reader pre-loaded with the large response
        async def mock_open(path, **kwargs):
            reader = asyncio.StreamReader(limit=262144)
            reader.feed_data(response_bytes)
            reader.feed_eof()
            writer = MagicMock()
            writer.drain = AsyncMock()
            writer.wait_closed = AsyncMock()
            return reader, writer

        with patch("aegis.web.server.asyncio.open_unix_connection", mock_open):
            result = await _forge_socket_cmd("FORGE:LIST")

        assert result.startswith("FORGE:LIST:")
        parsed = json.loads(result[len("FORGE:LIST:"):])
        assert len(parsed) == 120

    @pytest.mark.asyncio
    async def test_large_response_passes_task_json(self):
        """Parsing large forge list returns valid task data."""
        import asyncio
        from unittest.mock import AsyncMock
        from aegis.web.server import _forge_socket_cmd

        # 2 tasks with verbose diff data -> large but plausible
        tasks = [
            {
                "id": "abc123",
                "status": "completed",
                "spec": "implement login endpoint",
                "diffs": [{"path": f"src/file{i}.py", "content": "x" * 5000} for i in range(30)],
                "files_created": [f"src/new{i}.py" for i in range(10)],
                "files_modified": [f"src/mod{i}.py" for i in range(5)],
            },
            {
                "id": "def456",
                "status": "completed",
                "spec": "add error handling",
                "diffs": [{"path": f"src/err{i}.py", "content": "y" * 3000} for i in range(15)],
                "files_created": [],
                "files_modified": [f"src/handler{i}.py" for i in range(8)],
            },
        ]
        payload = json.dumps(tasks)
        assert len(payload) > 65536, f"payload {len(payload)} bytes < 64KB"

        response = f"FORGE:LIST:{payload}\n"
        response_bytes = response.encode()

        async def mock_open(path, **kwargs):
            reader = asyncio.StreamReader(limit=262144)
            reader.feed_data(response_bytes)
            reader.feed_eof()
            writer = MagicMock()
            writer.drain = AsyncMock()
            writer.wait_closed = AsyncMock()
            return reader, writer

        with patch("aegis.web.server.asyncio.open_unix_connection", mock_open):
            result = await _forge_socket_cmd("FORGE:LIST")

        assert result.startswith("FORGE:LIST:")
        parsed = json.loads(result[len("FORGE:LIST:"):])
        assert len(parsed) == 2
        assert parsed[0]["id"] == "abc123"
        assert len(parsed[0]["diffs"]) == 30
        assert parsed[1]["id"] == "def456"
        assert len(parsed[1]["diffs"]) == 15


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
            json={"approve": True},
            params=AUTH_PARAMS,
        )
        assert "FORGE:GATE:abc123:true" in mock_forge_socket.commands_received

    def test_cleanup_maps_to_forge_cleanup(self, mock_forge_socket):
        client = TestClient(app)
        client.post("/forge/abc123/cleanup", params=AUTH_PARAMS)
        assert "FORGE:CLEANUP:abc123" in mock_forge_socket.commands_received


# ---- Buffer-limit regression tests ----
#
# _forge_socket_cmd calls open_conn(path, limit=262144) to support responses
# larger than the default StreamReader buffer (64 KiB).  Without the larger
# limit, the reader may stall or truncate on large FORGE:LIST payloads.


class TestBufferLimit:
    """Regression: _forge_socket_cmd buffer limit and large-response handling."""

    async def test_open_conn_receives_limit_param(self):
        """open_unix_connection must be called with limit=262144."""
        from unittest.mock import AsyncMock

        mock_reader = AsyncMock()
        mock_reader.readline.return_value = b"FORGE:OK:abc123\n"

        class _MockWriter:
            async def drain(self):
                pass

            async def wait_closed(self):
                pass

            def write(self, _data: bytes) -> None:
                pass

            def close(self) -> None:
                pass

        mock_writer = _MockWriter()

        with patch("asyncio.open_unix_connection", new_callable=AsyncMock) as mo:
            mo.return_value = (mock_reader, mock_writer)
            from aegis.web.server import _forge_socket_cmd
            resp = await _forge_socket_cmd("FORGE:SUBMIT:test")

        assert resp == "FORGE:OK:abc123"
        mo.assert_awaited_once()
        _args, kwargs = mo.await_args
        assert kwargs.get("limit") == 262144, (
            f"Expected limit=262144, got {kwargs.get('limit')}"
        )

    def test_large_list_response_handled(self):
        """/forge/list must handle FORGE:LIST payloads larger than 64 KiB."""
        import json as _json

        client = TestClient(app)
        # Build a task list whose JSON serialization exceeds 64 KiB
        large_tasks = [{"id": f"task-{i}", "status": "completed"} for i in range(2000)]
        payload = _json.dumps(large_tasks)
        assert len(payload) > 65536, f"payload {len(payload)} bytes, need >65536"

        async def large_list(_cmd: str) -> str:
            return f"FORGE:LIST:{payload}"

        with patch("aegis.web.server._forge_socket_cmd", side_effect=large_list):
            resp = client.get("/forge/list", params=AUTH_PARAMS)

        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)
        assert len(data["tasks"]) == 2000
        assert data["tasks"][0]["id"] == "task-0"

    def test_large_diff_response_handled(self):
        """/forge/{id}/diff must handle FORGE:RESULT payloads larger than 64 KiB."""
        client = TestClient(app)
        large_payload = "x" * 70000
        expected = f'FORGE:RESULT:{{"data": "{large_payload}"}}'

        async def large_diff(_cmd: str) -> str:
            return expected

        with patch("aegis.web.server._forge_socket_cmd", side_effect=large_diff):
            resp = client.get("/forge/abc123/diff", params=AUTH_PARAMS)

        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert len(data["data"]) == 70000
