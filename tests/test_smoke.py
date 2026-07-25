"""End-to-end smoke test.

Fires a synthetic PermissionRequest at a running bridge (an in-process ASGI app),
answers it through an injected fake transport, and asserts the returned JSON
matches the shape documented in CLAUDE.md.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
from bridge import create_app
from models import ALLOW, DENY
from tests.fake_transport import FakeTransport

_PAYLOAD = {
    "session_id": "sess-1",
    "cwd": "/home/tharu/starsat/em",
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf /home/tharu/starsat/build"},
}


def _expected(behavior: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": behavior},
        }
    }


def _client(transport, tmp_path):
    app = create_app(transport, trace_path=str(tmp_path / "trace.jsonl"))
    return TestClient(app)


@pytest.mark.smoke
def test_permission_request_denied_through_fake_transport(tmp_path):
    fake = FakeTransport(DENY)  # test supplies the decision explicitly
    resp = _client(fake, tmp_path).post(config.HOOK_PATH, json=_PAYLOAD)

    assert resp.status_code == 200
    assert resp.json() == _expected("deny")
    assert len(fake.screens) == 1 and len(fake.screens[0]) == config.ROWS  # it rendered a frame
    assert fake.idle_calls == 1  # display returned to idle after the decision


@pytest.mark.smoke
def test_permission_request_allowed_through_fake_transport(tmp_path):
    fake = FakeTransport(ALLOW)  # explicit allow proves the allow shape passes through
    resp = _client(fake, tmp_path).post(config.HOOK_PATH, json=_PAYLOAD)

    assert resp.status_code == 200
    assert resp.json() == _expected("allow")


@pytest.mark.smoke
def test_malformed_body_returns_200_deny(tmp_path):
    # Fail-closed: a body that would 422 under Pydantic must still be a 200 deny,
    # never a non-2xx that Claude Code treats as non-blocking (i.e. allow).
    resp = _client(FakeTransport(ALLOW), tmp_path).post(
        config.HOOK_PATH, content=b"not json", headers={"content-type": "application/json"}
    )

    assert resp.status_code == 200
    assert resp.json() == _expected("deny")


@pytest.mark.smoke
def test_internal_timeout_returns_200_deny(tmp_path, monkeypatch):
    # A transport that never answers in time must resolve to a 200 deny.
    monkeypatch.setattr(config, "DECISION_TIMEOUT_S", 0.05)
    fake = FakeTransport(ALLOW, delay=5.0)
    resp = _client(fake, tmp_path).post(config.HOOK_PATH, json=_PAYLOAD)

    assert resp.status_code == 200
    assert resp.json() == _expected("deny")
