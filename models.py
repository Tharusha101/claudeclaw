"""Frozen dataclasses for anything crossing a module boundary.

Phase 1 needs exactly two shapes: the parsed PermissionRequest event and the
allow/deny Decision. Cost snapshots come with OTLP in a later phase and are
deliberately absent here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Behavior = Literal["allow", "deny"]


@dataclass(frozen=True, slots=True)
class Decision:
    """A single approve/deny outcome. The only two values a hook may return."""

    behavior: Behavior


# Canonical instances. There is intentionally no ALLOW default anywhere in the
# control flow — fail-closed means DENY is what every non-answer path returns.
ALLOW = Decision("allow")
DENY = Decision("deny")


@dataclass(frozen=True, slots=True)
class PermissionRequestEvent:
    """A PermissionRequest hook payload, parsed defensively.

    `tool_input` shape varies by tool (Bash -> {command}, Write -> {file_path,
    content}, MCP tools differ), so it stays a mapping and `render` decides what
    to surface.
    """

    session_id: str
    cwd: str
    tool_name: str
    tool_input: Mapping[str, Any]
    hook_event_name: str = "PermissionRequest"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PermissionRequestEvent:
        """Build from a decoded JSON body. Lenient: a sparse-but-valid payload
        still prompts the human (better than an auto-deny). Only truly broken
        input (non-JSON) fails upstream in the handler and denies.
        """
        tool_input = data.get("tool_input")
        return cls(
            session_id=str(data.get("session_id", "")),
            cwd=str(data.get("cwd", "")),
            tool_name=str(data.get("tool_name") or "?"),
            tool_input=dict(tool_input) if isinstance(tool_input, Mapping) else {},
        )
