"""Pure approval logic. No I/O, no async, no framework imports.

Two responsibilities, both fail-closed:

- `resolve`: map an interaction outcome to a final Decision. Anything that is
  not a clean, explicit answer denies.
- `accepts`: the generation gate. A keystroke read while an earlier prompt was
  on screen must never answer a later prompt. Each prompt is issued under a
  monotonic generation; an answer stamped with a superseded generation is
  discarded rather than applied. This is the fix for the "late 'y' eats the
  next prompt's answer" failure — a silent wrong approval, the exact class this
  project exists to prevent.

Phase 2 keeps this module: once the transport is BLE, decisions arrive
asynchronously and request/response stops being the correlation. The generation
is what stays correct when that happens.
"""

from __future__ import annotations

from enum import Enum

from models import DENY, Decision


class Outcome(Enum):
    ANSWERED = "answered"
    TIMEOUT = "timeout"
    ERROR = "error"


def resolve(outcome: Outcome, answer: Decision | None) -> Decision:
    """Final decision for an interaction. Only a clean answered outcome carrying
    an explicit Decision survives; timeout, error, and a missing answer all deny.
    """
    if outcome is Outcome.ANSWERED and answer is not None:
        return answer
    return DENY


def accepts(current: int, incoming: int) -> bool:
    """True iff an answer stamped `incoming` still belongs to the live prompt
    `current`. A stale answer from a superseded generation is rejected.
    """
    return current == incoming
