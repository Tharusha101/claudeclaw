# Named Cloudflare tunnel — the hardened "away" setup

Run once you have a domain on Cloudflare. This gives a **stable hostname** (no
reflashing on restart), exposes **only `/keytag`** (the `/hooks` endpoint stays
private), and lets the keytag **validate the cert**. It closes all three gaps of
the quick-tunnel proof.

## 1. Authenticate and create the tunnel (one time)

```sh
cloudflared tunnel login                 # opens a browser; pick your domain
cloudflared tunnel create crabtag        # prints a TUNNEL_ID and writes <ID>.json
```

## 2. Config

Copy `config.example.yml` to `config.yml`, set `tunnel:` / `credentials-file:`
to the `TUNNEL_ID`, and set the hostname (e.g. `keytag.yourdomain.com`). Route
DNS to the tunnel:

```sh
cloudflared tunnel route dns crabtag keytag.yourdomain.com
```

## 3. Run

```sh
# on the PC — bridge stays on localhost; the tunnel reaches it there
KEYTAG_TOKEN=<same-token> uv run python bridge.py --ws
cloudflared tunnel --config config.yml run crabtag
```

## 4. Pin the cert (validate TLS)

Grab the ROOT CA of the edge cert and paste it into `firmware/src/secrets.h` as
`BRIDGE_CA_CERT` (see secrets.h.example). Get the chain with:

```sh
openssl s_client -connect keytag.yourdomain.com:443 -servername keytag.yourdomain.com -showcerts </dev/null
```

Take the **root** of the chain (for Cloudflare Universal SSL this is often
`GTS Root R4` / `ISRG Root X1`), and set it in `secrets.h` — as a **variable + a
flag**, not a bare `#define` (a multi-line raw string in a macro breaks the
preprocessor):

```c
#define BRIDGE_HOST "keytag.yourdomain.com"
#define BRIDGE_PORT 443
#define BRIDGE_TLS  1
#define BRIDGE_HAS_CA 1
static const char BRIDGE_CA_CERT[] = R"EOF(
-----BEGIN CERTIFICATE-----
...root CA...
-----END CERTIFICATE-----
)EOF";
```

Then `pio run -e esp32-c3-wifi -t upload`. With `BRIDGE_HAS_CA` set the firmware
uses `beginSslWithCA` and rejects any cert that doesn't chain to that root. It
NTP-syncs time on WiFi connect so the cert's validity dates verify. If Cloudflare
later rotates to a different CA family, re-extract and reflash.

## 5. Use it

Phone hotspot on → keytag joins it → reaches `wss://keytag.yourdomain.com/keytag`
from anywhere. Prompts appear on the keytag; buttons answer them.

## Always-on tunnel (Windows)

`cloudflared service install` does **not** work for a *locally-managed* tunnel on
Windows — it registers a bare `cloudflared.exe` service with no `tunnel run`
command, which just crash-loops. Use a **logon scheduled task** running the
proven `tunnel run` instead (elevated PowerShell, once):

```powershell
$exe = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$action  = New-ScheduledTaskAction -Execute $exe -Argument 'tunnel --config "C:\Users\<you>\.cloudflared\config.yml" run crabtag'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "crabtag-tunnel" -Action $action -Trigger $trigger -Settings $settings -User "$env:USERNAME" -RunLevel Limited -Force
Start-ScheduledTask -TaskName "crabtag-tunnel"
```

Survives reboots; runs while you're logged in. The **bridge** (`bridge.py --ws`)
is the other half — start it when you're working. For run-while-logged-out you'd
need the token-based service (`cloudflared service install <token>`) with ingress
configured in the Cloudflare dashboard instead of `config.yml`.
