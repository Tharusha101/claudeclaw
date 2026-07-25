"""Pure unit tests for the approval logic. No server, no async."""

from __future__ import annotations

from approvals import Outcome, accepts, resolve
from models import ALLOW, DENY


def test_answered_returns_the_explicit_decision():
    assert resolve(Outcome.ANSWERED, ALLOW) is ALLOW
    assert resolve(Outcome.ANSWERED, DENY) is DENY


def test_timeout_denies():
    assert resolve(Outcome.TIMEOUT, None) is DENY


def test_error_denies():
    assert resolve(Outcome.ERROR, None) is DENY


def test_answered_without_a_decision_denies():
    # Belt-and-suspenders: an "answered" outcome with no payload still fails closed.
    assert resolve(Outcome.ANSWERED, None) is DENY


def test_generation_gate_accepts_the_live_prompt():
    assert accepts(current=2, incoming=2) is True


def test_late_answer_does_not_affect_the_next_generation():
    # Issue gen 1, time it out (advance to gen 2), then deliver a late gen-1
    # answer. It must be discarded, while a gen-2 answer is accepted.
    current = 1
    current = 2  # gen 1 timed out; the live prompt is now gen 2

    assert accepts(current=current, incoming=1) is False  # late gen-1 keystroke rejected
    assert accepts(current=current, incoming=2) is True  # a real gen-2 answer applies
