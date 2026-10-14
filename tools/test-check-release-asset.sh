#!/usr/bin/env bash
# Tests tools/check-release-asset.sh with the real release asset and
# damaged copies of it. No network.
#
#   tools/test-check-release-asset.sh ASSET_FILE
#
# ASSET_FILE is the reviewed asset (tam-downloads-e3d036a6f643.tar.gz).

set -uo pipefail
cd "$(dirname "$0")/.."
ASSET=$(realpath -- "${1:?usage: tools/test-check-release-asset.sh ASSET_FILE}")
ID=downloads-e3d036a6f643
NAME=tam-downloads-e3d036a6f643.tar.gz
W=$(mktemp -d)
trap 'rm -rf -- "$W"' EXIT
PASS=0 FAIL=0
run() { # NAME EXPECTED_EXIT FILE
    local out rc
    out=$(tools/check-release-asset.sh "$ID" "$3" 2>&1); rc=$?
    if [ "$rc" = "$2" ]; then PASS=$((PASS + 1)); echo "PASS $1 (exit $rc)"
    else FAIL=$((FAIL + 1)); echo "FAIL $1 (exit $rc, want $2)"; printf '%s\n' "$out" | sed 's/^/    | /'; fi
}
variant() { mkdir -p "$W/$1"; echo "$W/$1/$NAME"; }

run A01 0 "$ASSET"
cp "$ASSET" "$W/other-name.tar.gz"; run A02 2 "$W/other-name.tar.gz"
f=$(variant corrupt); cp "$ASSET" "$f"; printf '\x00' | dd of="$f" bs=1 seek=1000 conv=notrunc 2>/dev/null; run A03 2 "$f"
f=$(variant short); head -c 1000000 "$ASSET" >"$f"; run A04 2 "$f"
run A05 1 "$W/missing/$NAME"
# Hostile archives cannot carry the recorded SHA-256; the entry checks are
# exercised by a temporary record that pins the hostile file's own hash.
python3 -I - "$ASSET" "$W" <<'PY'
import io, sys, tarfile
src, out = sys.argv[1], sys.argv[2]
with tarfile.open(src, "r:gz") as t:
    base = [(m, t.extractfile(m).read() if m.isfile() else None) for m in t.getmembers()]
def write(name, extra):
    with tarfile.open("%s/%s.tar.gz" % (out, name), "w:gz", format=tarfile.GNU_FORMAT) as t:
        for m, d in base + extra:
            t.addfile(m, io.BytesIO(d) if d is not None else None)
link = tarfile.TarInfo("tam-downloads/downloads/link"); link.type = tarfile.SYMTYPE; link.linkname = "/etc/passwd"
write("symlink", [(link, None)])
evil = tarfile.TarInfo("tam-downloads/../evil"); evil.size = 1
write("dotdot", [(evil, b"x")])
extra = tarfile.TarInfo("tam-downloads/downloads/extra"); extra.size = 1
write("extra", [(extra, b"x")])
PY
for h in symlink dotdot extra; do
    hid=t-$h
    mkdir -p "releases/$hid" "$W/$hid"
    cp "$W/$h.tar.gz" "$W/$hid/$NAME"
    sed -e "s/^release_id=.*/release_id=$hid/" -e "s/^asset_size=.*/asset_size=$(stat -c %s "$W/$hid/$NAME")/" \
        -e "s/^asset_sha256=.*/asset_sha256=$(sha256sum <"$W/$hid/$NAME" | cut -d' ' -f1)/" \
        "releases/$ID/release.txt" >"releases/$hid/release.txt"
    out=$(tools/check-release-asset.sh "$hid" "$W/$hid/$NAME" 2>&1); rc=$?
    rm -rf "releases/$hid"
    if [ "$rc" = 2 ]; then PASS=$((PASS + 1)); echo "PASS H-$h refused (exit 2): ${out##*: }"
    else FAIL=$((FAIL + 1)); echo "FAIL H-$h (exit $rc, want 2)"; printf '%s\n' "$out" | sed 's/^/    | /'; fi
done
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
