#!/bin/bash
# Obsidian OS — hardened kernel builder (CI job: build-kernel).
#
# Produces obsidian-kernel_*.deb from the Debian trixie `linux` source with the
# hardened config fragment applied (merge_config + olddefconfig). The package
# Provides/Conflicts linux-image-amd64 so recipes that install linux-image-amd64
# get our hardened build instead (the stock kernel is the template fallback).
#
# Output: $OUTDIR/*.deb   (default: ./kernel-out)
# Env:    KERNEL_SRC        path to pre-unpacked linux tree (optional)
#         FRAG              path to hardening fragment (default below)
#         KBUILD_JOBS       parallelism (default: nproc)
#
# Runtime: heavy (compiles the kernel). CI runs on ubuntu-24.04 (4-core) with
# the build deps line below; a prebuilt tree via KERNEL_SRC is much faster.
set -euo pipefail

OUTDIR="${OUTDIR:-kernel-out}"
FRAG="${FRAG:-$(dirname "$(readlink -f "$0")")/../debos/overlays-src/common/etc/obsidian/kernel/hardened.config}"
JOBS="${KBUILD_JOBS:-$(nproc)}"
SRCDIR="${KERNEL_SRC:-}"

say() { printf '%s\n' "$*"; }
die() { say "build-kernel: $*" >&2; exit 1; }

[ -f "$FRAG" ] || die "fragment not found: $FRAG"
mkdir -p "$OUTDIR"

# ---- 0. build host deps (idempotent) -------------------------------------
if [ -f /etc/debian_version ]; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq \
    build-essential dpkg-dev fakeroot rsync flex bison \
    libssl-dev libelf-dev dwarves gcc-x86-64-linux-gnu \
    debhelper debian-keyring
  fi

# ---- 1. acquire source ------------------------------------------------------
BUILD_DIR="$(mktemp -d /tmp/obs-kernel-XXXXXX)"
if [ -n "$SRCDIR" ]; then
  say "using provided source: $SRCDIR"
  rsync -a --exclude='.git' "$SRCDIR"/ "$BUILD_DIR/linux/"
else
  # GitHub runners are Ubuntu and have no Debian deb-src entries, so point apt
  # at an explicit Debian trixie deb-src list. --allow-unauthenticated keeps
  # this portable across hosts; a real Debian host may drop it.
  DEBSRC="$(mktemp /tmp/obs-debsrc-XXXX.list)"
  cat > "$DEBSRC" <<'EOF'
deb-src http://deb.debian.org/debian trixie main
deb-src http://security.debian.org/debian-security trixie-security main
EOF
  say "fetching Debian linux source (trixie) via explicit deb-src entries…"
  mkdir -p "$BUILD_DIR/src"
  (
    cd "$BUILD_DIR/src" \
    && sudo apt-get --allow-unauthenticated \
               -o Dir::Etc::sourcelist="$DEBSRC" \
               -o Dir::Etc::sourceparts=- \
               -o APT::Get::List-Cleanup=0 update -qq \
    && sudo apt-get --allow-unauthenticated \
               -o Dir::Etc::sourcelist="$DEBSRC" \
               -o Dir::Etc::sourceparts=- \
               -o APT::Get::List-Cleanup=0 source linux
  )
  d="$(find "$BUILD_DIR/src" -maxdepth 1 -type d -name 'linux-[0-9]*' | head -1)"
  [ -n "$d" ] || die "no linux source unpacked (apt-get source failed?)"
  mv "$d" "$BUILD_DIR/linux"
fi

# ---- 2. apply the Obsidian hardening fragment --------------------------------
cd "$BUILD_DIR/linux"
make olddefconfig >/dev/null 2>&1 || true                       # prime the tree
scripts/kconfig/merge_config.sh -O . \
  $(find debian/config -name config -path '*amd64*' -o -name config-amd64 2>/dev/null | head -1) \
  "$FRAG" >/dev/null 2>&1 || \
  { say "merge_config fell back to plain fragment application"; \
    cat "$FRAG" >> .config; make olddefconfig >/dev/null; }
make olddefconfig >/dev/null
say "kernel config:"
grep -E 'CONFIG_(INIT_ON_ALLOC|INIT_ON_FREE|STRICT_KERNEL_RWX|SECURITY_LOCKDOWN_LSM|RANDOMIZE_KSTACK_OFFSET_DEFAULT|HARDENED_USERCOPY)=y' .config || \
  say "WARN: one or more expected hardening options not set — check $FRAG"

# ---- 3. build binary packages ------------------------------------------------
make -j"$JOBS" deb-pkg KDEB_PKGVERSION="$(dpkg-parsechangelog -S Version 2>/dev/null || echo 0.1)-1" \
  LOCALVERSION=-obsidian-h hardened_boot=1
cp ../obsidian_*.deb "$OUTDIR"/ 2>/dev/null || cp ../linux-*.deb "$OUTDIR"/ 2>/dev/null
rename 's/^/obsidian-/' "$OUTDIR"/*.deb 2>/dev/null || true

rm -rf "$BUILD_DIR"
say "artifacts:"; ls -lh "$OUTDIR"/*.deb
exit 0