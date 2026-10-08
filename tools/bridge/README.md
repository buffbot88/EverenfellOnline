# mko-ws-tcp-bridge

WebSocket ↔ raw TCP forwarder so the original Flash client (under Ruffle,
which cannot open raw TCP) reaches the unmodified legacy game server on
`:8008`. Transport-only: never parses, builds, or alters game packets.

```sh
cd tools/bridge
npm install
npm start            # ws://127.0.0.1:8181 -> 127.0.0.1:8008
npm test             # 10 transport/protocol tests vs a fake TCP server
```

## Configuration (env)

| Var | Default | Purpose |
|---|---|---|
| `LEGACY_HOST` / `LEGACY_PORT` | `127.0.0.1` / `8008` | game server TCP endpoint |
| `BRIDGE_HOST` / `BRIDGE_PORT` | `127.0.0.1` / `8181` | where the bridge listens |
| `LOG_LEVEL` | `info` | `info`\|`warn`\|`error` |
| `LOG_PACKETS` | off | dev-only per-frame log: direction, length, kind, first 96 bytes hex |

Packet payloads may carry session tokens: `LOG_PACKETS=1` prints a warning
and is meant for local capture only (it produced the documented INITKEY
frame in `docs/protocol.md`). Lengths/counts always log; policy-handshake
frames are labelled, never fully dumped.

## Wire protocol

websockify-compatible (what Ruffle's `socketProxy` expects): each WebSocket
connection gets its own TCP connection; binary WS messages ↔ TCP bytes with
no preamble. Legacy base64 text frames are accepted and decoded. TCP refusal
closes the WS with code 1011. See `docs/protocol.md` for the game framing
(u32be length + AMF3) — the bridge deliberately knows nothing about it.

## Files

- `bridge.js` — the forwarder (`start(opts)` is importable for tests).
- `test/bridge.test.js` — `node --test`: connect, both directions, multi +
  large (256 KB) messages, split/coalesced TCP writes, policy passthrough,
  client isolation, clean shutdown, TCP-refused reporting.
- `test/fake-game-server.js` — deterministic stand-in for integration runs
  (logs connections, answers `policy-file-request` in-band like NetListener).
