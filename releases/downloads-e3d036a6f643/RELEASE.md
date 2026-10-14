# downloads-e3d036a6f643 — TAM edge test client download bundle

This release carries one asset, the download tree served by the TAM Center at `https://tam.pmr.vn/downloads/`. The TAM Center download server retrieves this asset, checks it against a pin kept in the reviewed TAM Center source and only then publishes it. Technicians download from `https://tam.pmr.vn/downloads/`, not from this release.

**Test software.** The edge test client is not the TAM agent or probe. It has no service, no automatic or Center-managed update and no Windows build.

## Asset

| File | Bytes | SHA-256 |
|---|---|---|
| `tam-downloads-e3d036a6f643.tar.gz` | 11,786,806 | `661937b47e29d6b5038a14d07dc8f45f1896b5b6083783d0937dd127ce911eef` |

## Contents

| Served file | Bytes | SHA-256 |
|---|---|---|
| `testclient/ae4cda290ab18ff5db871b85e0063a835e27fec8/tam-edge-testclient-linux-amd64` | 11,110,012 | `12f774512bf7fb8a87accf61c882360aa56f67be897c48c81cc2f6ab9d67a473` |
| `testclient/ae4cda290ab18ff5db871b85e0063a835e27fec8/tam-edge-testclient-linux-arm64` | 10,276,881 | `592bbe49526ea8f5ea06cb9a396d1343798b28c389ed36f06759430064304919` |
| `testclient/ae4cda290ab18ff5db871b85e0063a835e27fec8/SHA256SUMS` | 196 | `5cf72ad90b487b6099b7725be0080ad08fdccd898b8ce79eb3c08fd226df27b2` |
| `installer/e3d036a6f64321fce28f8ed028a9870ae627dd54/tam-testclient-install.sh` | 18,922 | `979efbfbad3356b97e03bf8d9099fca2ba51dba98f9ce44207f16aa8ea941fe3` |
| `installer/e3d036a6f64321fce28f8ed028a9870ae627dd54/SHA256SUMS` | 92 | `c5912f443b16a6af5188911d14d7fc02ec44f44700bcde80bbfbff4dde47917e` |
| `index.html` | 3,668 | `b2c9ef5340f6789086b6644b54a51216609956d6efb541c81f048761e517fabb` |

The archive also holds `TREE-SHA256SUMS` (SHA-256 `d02b3e9c3d566f0f19415e5beef45859c28705225e28595afa325ac6e20eb730`) and the server-side publisher `publish-downloads.sh` (SHA-256 `f534075f5022465f7bd3d5d78090e80a4d7c0e2489521d68b6a9ccb9aaefd399`), which are not served.

## Provenance

- Test client binaries: built from TAM Center source commit `ae4cda290ab18ff5db871b85e0063a835e27fec8` (private repository), unchanged since their review.
- Installer: TAM Center source commit `e3d036a6f64321fce28f8ed028a9870ae627dd54`.
- The archive is deterministic; it was rebuilt byte for byte from those commits before this release.
- Integrity is a pinned size and SHA-256, not a cryptographic signature.

Installation: [docs/install-test-client.md](../../docs/install-test-client.md).
