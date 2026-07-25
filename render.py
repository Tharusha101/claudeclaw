"""Pure rendering: PermissionRequestEvent -> exactly 8 lines of <= 20 chars.

No I/O, no async, no framework imports. The device draws whatever this returns,
verbatim; iterating on layout must never require reflashing a board.

Layout (20 cols x 8 rows):

    row 1     tool name (left), queue depth (right)
    row 2     divider
    rows 3-5  payload: truncate to fit 60, then wrap to 20
    row 6     context (secondary detail, or compact cwd)
    row 7     divider
    row 8     deny / allow affordance

Payload extraction is per-field-type, because truncation direction is a
property of the field, not the tool:

    Bash                  -> command,      truncate MIDDLE (verb and target both matter)
    Edit / Write / Read   -> file_path,    truncate LEFT   (the tail carries meaning)
    WebFetch / WebSearch  -> url host,     no truncation   (the host IS the decision)
    mcp__<server>__<tool> -> server,       no truncation   (the server is the trust boundary)
    anything unrecognized -> "? unknown payload"

Load-bearing fallback: an unrecognized tool renders "? unknown payload", never a
scraped-together summary. If we cannot tell the human what they are approving,
the screen must say so rather than look reassuring.
"""

from __future__ import annotations

from enum import Enum, auto
from urllib.parse import urlparse

import config
from models import PermissionRequestEvent


class _Trunc(Enum):
    MIDDLE = auto()
    LEFT = auto()
    NONE = auto()


def render(event: PermissionRequestEvent, queue_depth: int) -> list[str]:
    """The full frame. Always exactly `config.ROWS` lines, each <= `config.COLS`."""
    rows = [
        _header(event, queue_depth),
        config.DIVIDER,
        *_payload_rows(event),
        _context(event),
        config.DIVIDER,
        config.AFFORDANCE,
    ]
    # Defensive clamp: the device draws these as-is, so never emit an over-wide line.
    return [row[: config.COLS] for row in rows]


def _display_name(event: PermissionRequestEvent) -> str:
    if event.tool_name.startswith("mcp__"):
        return "mcp"
    return event.tool_name


def _header(event: PermissionRequestEvent, queue_depth: int) -> str:
    right = f"{queue_depth} {config.QUEUE_GLYPH}"
    max_name = config.COLS - len(right) - 1  # keep at least one separating space
    name = _display_name(event)
    if len(name) > max_name:
        name = name[:max_name]
    pad = config.COLS - len(name) - len(right)
    return name + " " * pad + right


def _payload_rows(event: PermissionRequestEvent) -> list[str]:
    text, direction = _extract(event)
    text = _truncate(text, config.PAYLOAD_BUDGET, direction)
    lines = _wrap(text, config.COLS)[: config.PAYLOAD_ROWS]
    while len(lines) < config.PAYLOAD_ROWS:
        lines.append("")
    return lines


def _extract(event: PermissionRequestEvent) -> tuple[str, _Trunc]:
    name = event.tool_name
    ti = event.tool_input

    if name == "Bash":
        command = ti.get("command")
        if isinstance(command, str) and command:
            return command, _Trunc.MIDDLE

    elif name in ("Edit", "Write", "Read"):
        file_path = ti.get("file_path")
        if isinstance(file_path, str) and file_path:
            return file_path, _Trunc.LEFT

    elif name in ("WebFetch", "WebSearch"):
        url = ti.get("url")
        if isinstance(url, str) and url:
            host = urlparse(url).hostname or url
            return host, _Trunc.NONE
        query = ti.get("query")  # WebSearch carries a query, not a url
        if isinstance(query, str) and query:
            return query, _Trunc.MIDDLE

    elif name.startswith("mcp__"):
        parts = name.split("__")
        server = parts[1] if len(parts) > 1 and parts[1] else name
        return server, _Trunc.NONE

    # Unrecognized tool, or a known tool missing its field: say so plainly.
    return config.UNKNOWN_PAYLOAD, _Trunc.NONE


def _context(event: PermissionRequestEvent) -> str:
    if event.tool_name == "Write":
        content = event.tool_input.get("content")
        if isinstance(content, str):
            return f"+{content.count(chr(10)) + 1} lines"
    if event.cwd:
        return _truncate(event.cwd, config.COLS, _Trunc.LEFT)
    return ""


def _truncate(s: str, budget: int, direction: _Trunc) -> str:
    if len(s) <= budget:
        return s
    ellipsis = config.ELLIPSIS
    keep = budget - len(ellipsis)
    if keep <= 0:
        return s[:budget]
    if direction is _Trunc.LEFT:
        return ellipsis + s[len(s) - keep :]
    if direction is _Trunc.MIDDLE:
        head = (keep + 1) // 2
        tail = keep - head
        return s[:head] + ellipsis + (s[len(s) - tail :] if tail else "")
    # NONE fields are normally short; if one is pathological, clip the tail.
    return s[:keep] + ellipsis


def _wrap(s: str, width: int) -> list[str]:
    # Hard character wrap, deliberately: it preserves the exact characters being
    # approved. A prettier word wrap would collapse whitespace and could show the
    # human something subtly different from what actually runs.
    if not s:
        return [""]
    return [s[i : i + width] for i in range(0, len(s), width)]
