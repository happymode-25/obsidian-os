#!/bin/sh
# Assemble debos overlay tarballs from the overlay-src tree.
# Run from repo root:
#   ./scripts/make-overlays.sh
# Produces:
#   debos/overlays/common.tar        (every image)
#   debos/overlays/daily-driver.tar
#   debos/overlays/developer.tar
#   debos/overlays/pentester.tar     (gates consent - only installs the launcher,
#                                     tools ship disabled in the tools manifest)
#   debos/overlays/server.tar
#   debos/overlays/privacy-max.tar   (ghost/amnesic)
set -eu

SRC="debos/overlays-src"
OUT="debos/overlays"
mkdir -p "$OUT"

tar_out() { # $1 name $2 dir
    rm -f "$OUT/$1"
    tar --numeric-owner -cf "$OUT/$1" -C "$SRC/$2" .
    echo "-> $OUT/$1"
}

tar_out common.tar        common
tar_out daily-driver.tar  daily-driver
tar_out developer.tar     developer
tar_out pentester.tar     pentester
tar_out server.tar        server
tar_out privacy-max.tar   privacy-max

echo "overlays ready for: debos -t flavor:... debos/obsidian.yaml"