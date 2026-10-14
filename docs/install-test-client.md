# Installing the TAM edge test client (technicians)

This page is for a technician who installs the TAM edge test client on a Linux test machine. You need no TAM dashboard account and no GitHub account or token.

**State.** These instructions apply once the TAM coordinator has announced that the release below is published at `https://tam.pmr.vn/downloads/`. Until then the addresses answer with an error.

**What this is.** The edge test client is test software for the TAM test environment. It is not the TAM agent or probe: it installs no service and has no automatic or Center-managed update. Linux x86-64 (amd64) and ARM64 only; there is no Windows client.

## What you receive

From an authorized TAM operator, through a private channel (not a public chat, ticket or web page):

1. The installer commit and its SHA-256. For the current release:
   - installer commit `e3d036a6f64321fce28f8ed028a9870ae627dd54`
   - SHA-256 `979efbfbad3356b97e03bf8d9099fca2ba51dba98f9ce44207f16aa8ea941fe3`

   The same values are in this repository (`releases/downloads-e3d036a6f643/RELEASE.md`), which provides another place to compare the pins. These checksums are not a publisher signature; establish the expected values through the authorized operator before execution.
2. For a new test identity only: a one-time **enrollment link token** for exactly one device, created by the operator in the TAM Console. It expires (48 hours by default, adjustable from 1 to 168 hours) and is scoped to one device and one client, with bounded same-client retry. The operator can revoke or replace it. Keep it secret; it is never needed for installing or updating the program.

## Install or update the program

On the test machine, as `root`, paste the whole block:

```sh
( set -eu
  I=e3d036a6f64321fce28f8ed028a9870ae627dd54
  SUM=979efbfbad3356b97e03bf8d9099fca2ba51dba98f9ce44207f16aa8ea941fe3
  D=$(mktemp -d); trap 'rm -rf "$D"' EXIT
  curl -fsS --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 60 \
    -o "$D/install.sh" "https://tam.pmr.vn/downloads/installer/$I/tam-testclient-install.sh"
  echo "$SUM  $D/install.sh" | sha256sum -c -
  bash "$D/install.sh" install )
```

The installer checks the downloaded program against the size and SHA-256 written inside it, installs into `/root/tam-enrollment-test` and points `tam-edge-testclient` there at the new program. The same block updates an existing installation. It keeps every existing identity, key, request counter, heartbeat spool and token file, keeps the previous program for `rollback`, and does not stop or restart a running client. It ends with `INSTALLED <commit> <arch> <SHA-256>`. If the SHA-256 check fails, stop and report it; do not run the file.

Other commands of the installer, run the same way with `status` or `rollback` instead of `install`:

- `status` shows the installed build, the previous one and running clients.
- `rollback` switches back to the previous program. Identities and data are not changed.

## Enroll a new test identity

Only for a machine that does not have its identity yet. Put the token into a file readable only by root (paste it into an editor; do not type it on the command line), then:

```sh
cd /root/tam-enrollment-test
umask 077
./tam-edge-testclient enroll --server https://tam.pmr.vn/api/edge/v1 --state-dir state/<name> --token-file token.txt
rm -f token.txt
./tam-edge-testclient heartbeat run --state-dir state/<name>
```

`heartbeat run` works only after the TAM operator has enabled telemetry on the Center; otherwise it stops with a configuration error and the identity stays enrolled. Use a new `<name>` for each identity. Never copy a `state/<name>` directory to another machine or to another name: a copy is a second client with the same identity and the Center treats it as a conflict. Never run `reset` on an existing identity unless the TAM operator asks for it.

## Existing identities after an update

The installer leaves every `state/…` directory as it is. A running `heartbeat run` keeps using the program it started with: stop it (Ctrl-C) and start it again with the same `--state-dir`. No new enrollment is needed.

## What to report

The last line of the installer (`INSTALLED …`), the output of `status`, and any error message. Never send token files, `state/` contents or keys.
