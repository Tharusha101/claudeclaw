# crabtag bridge — phase 1

The thinnest end-to-end proof of the loop: Claude Code fires a
`PermissionRequest` hook, this bridge renders it as an 8×20 screen, a terminal
stub prints it and blocks on a keypress, and the decision returns as the hook
JSON. No hardware, no BLE, no cost tracking yet. See `CLAUDE.md` for the why.

## Run it

```sh
uv sync
uv run python bridge.py     # serves http://127.0.0.1:8787
```

`.claude/settings.json` already points the `PermissionRequest` hook at that URL,
so with the bridge running, a Claude Code tool prompt appears on the stub:

```
+--------------------+
|Bash             1 ||
|--------------------|
|rm -rf /home/tharu/s|
|tarsat/build && npm |
|ci                  |
|.../tharu/starsat/em|
|--------------------|
| x deny      allow v|
+--------------------+
[y] allow   [n] deny >
```

Press `y` to allow, `n` to deny. Anything else is ignored. If you don't answer
within `DECISION_TIMEOUT_S` (120s), the bridge denies and Claude Code moves on.

## Checks

```sh
uv run pytest            # everything
uv run pytest -m smoke   # end-to-end bridge smoke test
uv run ruff check .
uv run mypy .
```

Every hook event is appended to `trace.jsonl` (gitignored).
