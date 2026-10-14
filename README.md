# TAM Agent

Client software and release distribution for TAM (Telemetry, Alerting and Monitoring).

## Status

No managed TAM agent is published here yet. This repository currently distributes the reviewed **edge test client** download bundle used in the TAM test environment, as GitHub Release assets:

| Release | Content | State |
|---|---|---|
| `downloads-e3d036a6f643` | Edge test client build `ae4cda2…` (Linux amd64/arm64) and its installer `e3d036a…` | [Published prerelease](https://github.com/radionu/tam-agent/releases/tag/downloads-e3d036a6f643); public archive verified on 2026-10-14 |

The edge test client is test software: no service, no automatic or Center-managed update, no Windows build. The planned managed agent (outbound communication with TAM Center, enrollment, heartbeat telemetry and centrally managed updates) is not implemented here yet.

## Using it

- Technicians install from the TAM Center at `https://tam.pmr.vn/downloads/` with no dashboard account or GitHub token: [docs/install-test-client.md](docs/install-test-client.md).
- How releases are built, pinned and checked: [docs/releases.md](docs/releases.md).

## Development

Changes are developed on task branches and reviewed through pull requests. Keep documentation in English. Do not commit credentials, enrollment tokens, private keys, device state, customer data or release archives (they are attached to GitHub Releases).
