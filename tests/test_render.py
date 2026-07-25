"""Pure unit tests for rendering. No server, no async."""

from __future__ import annotations

import config
from models import PermissionRequestEvent
from render import render


def _event(
    tool_name: str, tool_input: dict, cwd: str = "/home/tharu/starsat/em"
) -> PermissionRequestEvent:
    return PermissionRequestEvent(
        session_id="s", cwd=cwd, tool_name=tool_name, tool_input=tool_input
    )


def test_frame_is_always_8_rows_of_at_most_20_cols():
    lines = render(_event("Bash", {"command": "ls"}), queue_depth=1)
    assert len(lines) == config.ROWS
    assert all(len(line) <= config.COLS for line in lines)


def test_header_shows_tool_name_and_queue_depth():
    header = render(_event("Bash", {"command": "ls"}), queue_depth=3)[0]
    assert header.startswith("Bash")
    assert header.rstrip().endswith(f"3 {config.QUEUE_GLYPH}")


def test_dividers_and_affordance_in_place():
    lines = render(_event("Bash", {"command": "ls"}), queue_depth=1)
    assert lines[1] == config.DIVIDER
    assert lines[6] == config.DIVIDER
    assert lines[7] == config.AFFORDANCE


def test_bash_command_truncates_from_the_middle():
    command = "rm -rf /home/tharu/projects/really/deep/path/build && npm ci && echo done"
    payload = "".join(render(_event("Bash", {"command": command}), 1)[2:5])
    assert config.ELLIPSIS in payload
    assert payload.startswith("rm -rf")  # dangerous verb survives
    assert payload.rstrip().endswith("done")  # and the tail survives too


def test_file_path_truncates_from_the_left():
    path = "/home/tharu/starsat/electrical/power/eps/bom_rev3_final_v2.csv"
    payload = "".join(render(_event("Write", {"file_path": path, "content": "a\nb"}), 1)[2:5])
    assert payload.startswith(config.ELLIPSIS)  # head dropped
    assert "bom_rev3_final_v2.csv" in payload  # meaningful tail kept


def test_write_context_shows_line_count():
    context = render(_event("Write", {"file_path": "/x.py", "content": "a\nb\nc"}), 1)[5]
    assert context == "+3 lines"


def test_webfetch_shows_host_not_path():
    payload = "".join(
        render(_event("WebFetch", {"url": "https://api.example.com/v1/secret/thing"}), 1)[2:5]
    )
    assert "example.com" in payload
    assert "secret" not in payload  # path dropped


def test_mcp_shows_server_segment_not_tool():
    lines = render(_event("mcp__memory__create_entities", {"entities": []}), 1)
    assert lines[0].startswith("mcp")
    payload = "".join(lines[2:5])
    assert "memory" in payload
    assert "create_entities" not in payload  # tool hidden; server is the trust boundary


def test_unrecognized_tool_says_unknown_rather_than_guessing():
    # The load-bearing fallback: do not scrape a reassuring-looking field.
    payload = "".join(
        render(_event("SomeNewTool", {"label": "safe cleanup", "command": "rm -rf /"}), 1)[2:5]
    )
    assert config.UNKNOWN_PAYLOAD in payload
    assert "safe cleanup" not in payload
