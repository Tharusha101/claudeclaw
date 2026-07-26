"""The mood hooks turn Claude Code events into idle-face moods."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bridge import create_app
from models import DENY
from tests.fake_transport import FakeTransport


def _client(fake):
    return TestClient(create_app(fake))


def test_prompt_submit_focuses():
    fake = FakeTransport(DENY)
    r = _client(fake).post("/hooks/user-prompt-submit", json={"session_id": "s"})
    assert r.status_code == 200
    assert fake.moods == ["FOCUS"]


def test_stop_goes_idle():
    fake = FakeTransport(DENY)
    _client(fake).post("/hooks/stop", json={"session_id": "s"})
    assert fake.moods == ["SLEEPY"]


def test_notification_goes_idle():
    fake = FakeTransport(DENY)
    _client(fake).post("/hooks/notification", json={"message": "idle"})
    assert fake.moods == ["SLEEPY"]


def test_stop_failure_is_dizzy():
    fake = FakeTransport(DENY)
    _client(fake).post("/hooks/stop-failure", json={"session_id": "s"})
    assert fake.moods == ["DIZZY"]
