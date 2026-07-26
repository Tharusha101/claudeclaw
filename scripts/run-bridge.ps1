# Always-on launcher for the crabtag bridge in --ws ("away") mode.
#
# Run by the crabtag-bridge scheduled task (see the "Always-on (Windows)"
# section in the top-level README) so the bridge -- and therefore plan-usage
# polling and the keytag's WebSocket link -- keeps running independent of any
# VS Code session or interactive terminal.
#
# KEYTAG_TOKEN is pulled from firmware/src/secrets.h (already the gitignored
# source of truth for the same token baked into the firmware build) so it
# isn't duplicated into a second secret store. Restarts bridge.py whenever it
# exits, so a crash or a transient failure doesn't end the loop -- only
# stopping the scheduled task does.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$secretsPath = Join-Path $repoRoot "firmware\src\secrets.h"
if (-not (Test-Path $secretsPath)) {
    throw "firmware/src/secrets.h not found -- copy secrets.h.example and fill it in first"
}
$match = Select-String -Path $secretsPath -Pattern '#define\s+KEYTAG_TOKEN\s+"([^"]+)"' | Select-Object -First 1
if (-not $match) {
    throw "KEYTAG_TOKEN not found in firmware/src/secrets.h"
}
$env:KEYTAG_TOKEN = $match.Matches[0].Groups[1].Value

$logPath = Join-Path $repoRoot "bridge.log"
while ($true) {
    "$(Get-Date -Format o) starting bridge.py --ws" | Add-Content -Path $logPath
    uv run python bridge.py --ws *>> $logPath
    "$(Get-Date -Format o) bridge.py exited with code $LASTEXITCODE, restarting in 5s" | Add-Content -Path $logPath
    Start-Sleep -Seconds 5
}
