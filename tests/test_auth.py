from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from aegis.web.server import app


@pytest.fixture(autouse=True)
def mock_token():
    with patch("aegis.web.server.HELIOS_TOKEN", "test-token-12345"):
        yield

def test_1_ws_state_query_token():
    client = TestClient(app)
    with client.websocket_connect("/state?token=test-token-12345") as websocket:
        data = websocket.receive_json()
        assert isinstance(data, dict)
        required_fields = [
            "neurobus", "h", "is_speaking", "last_action_type", "tick_id",
            "mnemosyne_event", "provider", "rpd_used", "rpd_budget", "connected",
            "uptime_seconds", "tick_rate", "pam", "coherence"
        ]
        for field in required_fields:
            assert field in data
        assert "runtime" in data

def test_2_ws_state_bearer_token():
    client = TestClient(app)
    with client.websocket_connect("/state", headers={"Authorization": "Bearer test-token-12345"}) as websocket:
        data = websocket.receive_json()
        assert isinstance(data, dict)
        required_fields = [
            "neurobus", "h", "is_speaking", "last_action_type", "tick_id",
            "mnemosyne_event", "provider", "rpd_used", "rpd_budget", "connected",
            "uptime_seconds", "tick_rate", "pam", "coherence"
        ]
        for field in required_fields:
            assert field in data

def test_3_ws_chat_query_token():
    client = TestClient(app)
    class MockStream:
        def write(self, data): pass
        async def drain(self): pass
        async def readline(self):
            return b"mocked-reply\n"
        def close(self): pass
        async def wait_closed(self): pass

    async def mock_connect(path):
        return MockStream(), MockStream()

    with patch("asyncio.open_unix_connection", mock_connect), \
         patch("pathlib.Path.exists", return_value=True):
        with client.websocket_connect("/chat?token=test-token-12345") as websocket:
            websocket.send_text("hello")
            data = websocket.receive_text()
            assert data == "mocked-reply"

def test_4_sse_logs_query_token():
    client = TestClient(app)
    async def mock_tail():
        yield {"schema_version": 1, "timestamp": "2026-06-07T16:03:42Z", "source": "aegis", "event_type": "error", "payload": {}, "severity": "error", "provenance": {}, "sensitivity": "internal"}

    with patch("aegis.web.server._tail_eventlog", mock_tail):
        resp = client.get("/logs?token=test-token-12345")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "data: {" in resp.text

def test_5_sse_logs_bearer_token():
    client = TestClient(app)
    async def mock_tail():
        yield {"schema_version": 1, "timestamp": "2026-06-07T16:03:42Z", "source": "aegis", "event_type": "error", "payload": {}, "severity": "error", "provenance": {}, "sensitivity": "internal"}

    with patch("aegis.web.server._tail_eventlog", mock_tail):
        resp = client.get("/logs", headers={"Authorization": "Bearer test-token-12345"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

def test_6_health_bearer_token():
    client = TestClient(app)
    resp = client.get("/health", headers={"Authorization": "Bearer test-token-12345"})
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data
    assert "connected" in data
    assert "runtime" in data

def test_7_ws_state_bad_token():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/state?token=bad-token") as websocket:
            websocket.receive_json()
    assert e.value.code == 4401

def test_8_ws_chat_bad_token():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/chat?token=bad-token") as websocket:
            websocket.receive_text()
    assert e.value.code == 4401

def test_9_sse_logs_bad_token():
    client = TestClient(app)
    resp = client.get("/logs?token=bad-token")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "auth_required"}

def test_10_health_query_token_rejected():
    client = TestClient(app)
    resp = client.get("/health?token=test-token-12345")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "auth_required"}


def test_11_cors_preflight_allowed_origin():
    client = TestClient(app)
    resp = client.options("/logs", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET"
    })
    assert resp.status_code == 204
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
    assert resp.headers.get("Access-Control-Allow-Credentials") == "true"
    assert "GET" in resp.headers.get("Access-Control-Allow-Methods", "")


def test_12_cors_preflight_preview_origin():
    client = TestClient(app)
    origin = "https://axis-dash-q66bs3qbn-navpreets-projects.vercel.app"
    resp = client.options("/logs", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "GET"
    })
    assert resp.status_code == 204
    assert resp.headers.get("Access-Control-Allow-Origin") == origin
    assert resp.headers.get("Access-Control-Allow-Credentials") == "true"


def test_13_cors_preflight_disallowed_origin():
    client = TestClient(app)
    origin = "https://axis-dash-q66bs3qbn-navpreets-projects.vercel.app.malicious.com"
    resp = client.options("/logs", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "GET"
    })
    assert resp.status_code == 204
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_14_ws_state_preview_origin_allowed():
    client = TestClient(app)
    origin = "https://axis-dash-q66bs3qbn-navpreets-projects.vercel.app"
    with client.websocket_connect("/state?token=test-token-12345", headers={"Origin": origin}) as websocket:
        data = websocket.receive_json()
        assert isinstance(data, dict)


def test_15_ws_state_disallowed_origin_rejected():
    client = TestClient(app)
    origin = "https://axis-dash-q66bs3qbn-navpreets-projects.vercel.app.malicious.com"
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/state?token=test-token-12345", headers={"Origin": origin}) as websocket:
            websocket.receive_json()
    assert e.value.code == 4401


def test_16_cors_preflight_git_branch_alias_origin():
    client = TestClient(app)
    origin = "https://axis-dash-git-fix-cors-navpreets-projects.vercel.app"
    resp = client.options("/logs", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "GET"
    })
    assert resp.status_code == 204
    assert resp.headers.get("Access-Control-Allow-Origin") == origin
    assert resp.headers.get("Access-Control-Allow-Credentials") == "true"


def test_17_cors_preflight_near_miss_origin_rejected():
    client = TestClient(app)
    origin = "https://axis-dash-x-evil-projects.vercel.app"
    resp = client.options("/logs", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "GET"
    })
    assert resp.status_code == 204
    assert "Access-Control-Allow-Origin" not in resp.headers

