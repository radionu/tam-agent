#!/usr/bin/env bash
# Checks a local release asset against its release record before it is
# attached to a GitHub Release, and prints the publication commands. It
# never publishes, tags or uploads anything and uses no network.
#
#   tools/check-release-asset.sh RELEASE_ID ASSET_FILE
#
# RELEASE_ID names releases/RELEASE_ID/release.txt in this repository.
# Checks: file name, exact size and SHA-256; every archive entry is a
# regular file or directory with a plain name below the archive root; the
# extracted files match TREE-SHA256SUMS, whose own SHA-256 and the
# publisher's SHA-256 match the record; no unlisted files.
#
# Exit codes: 0 asset matches; 1 usage or missing record; 2 mismatch.

set -euo pipefail
umask 077
export LC_ALL=C
cd "$(dirname "$0")/.."

die() { local rc=$1; shift; echo "check-release-asset: $*" >&2; exit "$rc"; }

[ $# = 2 ] || die 1 "usage: tools/check-release-asset.sh RELEASE_ID ASSET_FILE"
ID=$1 ASSET=$2
[[ $ID =~ ^[a-z0-9][a-z0-9._-]{0,99}$ ]] || die 1 "invalid release id"
REC=releases/$ID/release.txt
[ -f "$REC" ] || die 1 "no release record $REC"
[ -f "$ASSET" ] && [ ! -L "$ASSET" ] || die 1 "$ASSET is not a regular file"

declare -A R=()
while IFS= read -r line || [ -n "$line" ]; do
    case $line in '' | '#'*) continue ;; esac
    [[ $line =~ ^([a-z0-9_]+)=([A-Za-z0-9._/-]*)$ ]] || die 1 "malformed record line: $line"
    R[${BASH_REMATCH[1]}]=${BASH_REMATCH[2]}
done <"$REC"
for k in tag asset_name asset_size asset_sha256 archive_root publisher_sha256 tree_sums_sha256; do
    [ -n "${R[$k]:-}" ] || die 1 "record lacks $k"
done
[ "${R[release_id]:-}" = "$ID" ] || die 1 "record release_id differs from $ID"

[ "$(basename -- "$ASSET")" = "${R[asset_name]}" ] || die 2 "file name is not ${R[asset_name]}"
size=$(stat -c %s -- "$ASSET")
[ "$size" = "${R[asset_size]}" ] || die 2 "size $size, record says ${R[asset_size]}"
sum=$(sha256sum -- "$ASSET" | cut -d' ' -f1)
[ "$sum" = "${R[asset_sha256]}" ] || die 2 "SHA-256 $sum, record says ${R[asset_sha256]}"
echo "OK size and SHA-256"

root=${R[archive_root]}
names=$(tar -tzf "$ASSET") || die 2 "archive cannot be listed"
types=$(tar -tvzf "$ASSET" | cut -c1) || die 2 "archive cannot be listed"
[ "$(printf '%s\n' "$names" | wc -l)" = "$(printf '%s\n' "$types" | wc -l)" ] || die 2 "inconsistent listing"
[ -z "$(printf '%s\n' "$types" | grep -v -x '[-d]')" ] || die 2 "archive contains links or special files"
while IFS= read -r n; do
    [[ $n =~ ^$root(/[A-Za-z0-9_-][A-Za-z0-9._-]*)*/?$ ]] || die 2 "unsafe archive entry name"
done <<<"$names"
echo "OK archive entries (only plain files and directories below $root/)"

T=$(mktemp -d)
trap 'rm -rf -- "$T"' EXIT
tar -xzf "$ASSET" -C "$T" --no-same-owner --no-same-permissions
X=$T/$root
[ "$(sha256sum -- "$X/TREE-SHA256SUMS" | cut -d' ' -f1)" = "${R[tree_sums_sha256]}" ] || die 2 "TREE-SHA256SUMS differs from the record"
[ "$(sha256sum -- "$X/publish-downloads.sh" | cut -d' ' -f1)" = "${R[publisher_sha256]}" ] || die 2 "publisher differs from the record"
(cd "$X" && sha256sum --quiet -c TREE-SHA256SUMS) || die 2 "files do not match TREE-SHA256SUMS"
[ "$(cd "$X" && find downloads -type f | sort)" = "$(cut -c67- "$X/TREE-SHA256SUMS" | sort)" ] || die 2 "archive holds unlisted files"
echo "OK contents ($(wc -l <"$X/TREE-SHA256SUMS") served files)"

cat <<EOF

ASSET OK $ID

Publication (coordinator, after review; run from a clean checkout of the
reviewed main commit of ${R[repository]:-radionu/tam-agent}):

  git tag -a ${R[tag]} -m "${R[tag]}" <reviewed main commit>
  git push origin ${R[tag]}
  gh release create ${R[tag]} '$ASSET' --repo ${R[repository]:-radionu/tam-agent} \\
      --verify-tag --title ${R[tag]} --notes-file releases/$ID/RELEASE.md

Check after publication (any machine):

  curl -fsSL https://github.com/${R[repository]:-radionu/tam-agent}/releases/download/${R[tag]}/${R[asset_name]} | sha256sum
  # expected ${R[asset_sha256]}
EOF
