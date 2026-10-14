# Releases

This repository publishes reviewed TAM client deliveries as GitHub Release assets. It does not hold the binaries in Git history.

## What a release is

- One GitHub Release per delivery, tag `<release id>`, for example `downloads-e3d036a6f643`. The release id is a delivery name, not a product version number.
- One asset: a deterministic `tar.gz` archive whose single top directory is `tam-downloads/`. It holds the `downloads/` tree served at `https://tam.pmr.vn/downloads/`, the list `TREE-SHA256SUMS` of every served file and the server-side publisher `publish-downloads.sh`.
- A release record in `releases/<release id>/`: `release.txt` (asset name, size, SHA-256, contents hashes, source commits), `asset.sha256` and `RELEASE.md`, the release notes.

## Rules

- A published release and its asset never change. A different archive gets a new release id. Enabling GitHub's immutable releases setting on this repository is recommended; until it is enabled, immutability is enforced by the pins below, not by GitHub.
- The TAM Center download server does not trust this repository on its own. It reads the expected asset name, size and SHA-256 from a release descriptor in the reviewed TAM Center source, downloads the asset without any credential, refuses anything that differs, inspects every archive entry (only plain files and directories, no links, no `..`, no absolute or hidden names) before extracting, checks the contents again and only then publishes. A missing release or asset stops the server's procedure with an error; nothing is published.
- Integrity is a pinned size and SHA-256 over HTTPS. There is no cryptographic signature on these assets yet; signed releases are planned for the managed agent and are not available.
- Nothing in a release is secret: no tokens, keys, enrollment links, device state or customer data.

## Checking an asset before publication

```sh
tools/check-release-asset.sh <release id> <path to the asset file>
```

The tool checks the file name, size and SHA-256 against `releases/<release id>/release.txt`, inspects every archive entry, verifies the extracted files against `TREE-SHA256SUMS` and the hashes of `TREE-SHA256SUMS` and the publisher, and then prints the tag and `gh release create` commands to use. It never publishes anything. `tools/test-check-release-asset.sh <asset>` exercises it with the real asset and damaged copies.

## Checking a published asset

```sh
curl -fsSL https://github.com/radionu/tam-agent/releases/download/<release id>/<asset name> | sha256sum
```

The result must equal the SHA-256 in `releases/<release id>/asset.sha256`.
