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

Take the **last** certificate in the chain (the root), paste it as the PEM
`BRIDGE_CA_CERT`, and set in `secrets.h`:

```c
#define BRIDGE_HOST "keytag.yourdomain.com"
#define BRIDGE_PORT 443
#define BRIDGE_TLS  1
#define BRIDGE_CA_CERT R"EOF( ...root CA PEM... )EOF"
```

Then `pio run -e esp32-c3-wifi -t upload`. With `BRIDGE_CA_CERT` set the firmware
uses `beginSslWithCA` and rejects any cert that doesn't chain to that root.

## 5. Use it

Phone hotspot on → keytag joins it → reaches `wss://keytag.yourdomain.com/keytag`
from anywhere. Prompts appear on the keytag; buttons answer them.
