# TAM Agent

Client software and release distribution for TAM (Telemetry, Alerting and Monitoring).

## Status

This repository distributes the signed **Linux managed edge pilot 0.2.0-rc.1** and the earlier edge test client as GitHub Release assets:

| Release | Content | State |
|---|---|---|
| `managed-0.2.0-rc.1-b12c1a5` | Signed Linux managed runtime amd64/arm64 and Plesk download archive | [Published pilot prerelease](https://github.com/radionu/tam-agent/releases/tag/managed-0.2.0-rc.1-b12c1a5); owner deployment acceptance pending |
| `downloads-e3d036a6f643` | Edge test client build `ae4cda2…` (Linux amd64/arm64) and its installer `e3d036a…` | [Published prerelease](https://github.com/radionu/tam-agent/releases/tag/downloads-e3d036a6f643); public archive verified on 2026-10-14 |

The edge test client is test software: no service, no automatic or Center-managed update, no Windows build. The managed pilot includes supervised services, enrollment, outbound heartbeat telemetry, controlled runtime updates and supported legacy-client adoption. Bootstrap assets have separate platform release tags pinned to source commit `b12c1a563be3f740c721c02f7e78cda8449d03b6`. Obtain exact installation commands and independent trust pins from your TAM coordinator. Publishing a prerelease does not authorize automatic rollout. ARM64 is built and statically validated; real ARM execution remains untested.

For the managed pilot, see [managed installation](docs/install-managed-pilot.md). The instructions below refer to the earlier test client.

## Using it

- Technicians install from the TAM Center at `https://tam.pmr.vn/downloads/` with no dashboard account or GitHub token: [docs/install-test-client.md](docs/install-test-client.md).
- How releases are built, pinned and checked: [docs/releases.md](docs/releases.md).

## Development

Changes are developed on task branches and reviewed through pull requests. Keep documentation in English. Do not commit credentials, enrollment tokens, private keys, device state, customer data or release archives (they are attached to GitHub Releases).
