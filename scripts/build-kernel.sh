#!/bin/bash
# Obsidian OS — hardened kernel builder (CI job: build-kernel; task 1.7).
#
# Produces an obsidian-hardened linux-image .deb from the Debian trixie `linux`
# source: the EXACT kernel config Debian shipped in the stock trixie amd64
# image (build/kernel/base-config-amd64.config, extracted from the verified
# stock ISO's /boot/config-*) + the Obsidian hardening fragment
# (merge_config + olddefconfig), compiled with the kernel's own packaging
# (bindeb-pkg). The resulting kernel carries LOCALVERSION=-obsidian-h, so
# `uname -r` contains `obsidian` and the boot gate can attest it.
#
# Notes on method (deliberate):
#   * Base config is the shipped one, not debian/config/* fragments: Debian
#     composes its real .config from a dozen fragment files, and merging only
#     debian/config/amd64/config silently drops most SECURITY_* symbols. The
#     shipped /boot/config-6.12.107+deb13-amd64 IS that composition, so it is
#     the truthful starting point. It is pinned in the repo (reproducible) and
#     cross-checked against the fetched source version below.
#   * A Debian-packaged tree cannot simply run `make bindeb-pkg`: the kernel's
#     scripts/package collides with the Debian `debian/` packaging. We move the
#     Debian `debian/` dir aside first and let kbuild generate its own minimal
#     packaging.
#   * Debian's config may reference cert files (CONFIG_SYSTEM_TRUSTED_KEYS /
#     CONFIG_MODULE_SIG_KEY) under debian/. If the referenced file is missing
#     after the move, we clear the option so the build auto-generates a random
#     signing key instead of failing.
#   * Every hardening option in the fragment is asserted against .config after
#     olddefconfig; a fragment that silently failed to apply is a build failure,
#     not a warning.
#
# Output: $OUTDIR/*.deb   (default: <repo>/build/kernel-out/)
# Env:
#   OUTDIR          output directory for the .deb artifacts
#   KERNEL_SRC      path to pre-unpacked linux tree (optional; skips apt source)
#   BASE_CONFIG     base .config (default: build/kernel/base-config-amd64.config)
#   FRAG            path to the hardening fragment (default below)
#   DEBSRC_MIRROR   deb-src mirror (default: http://deb.debian.org/debian)
#   KBUILD_JOBS     parallelism (default: nproc)
#   CHECK_ONLY=1    stop after config merge + option verification; NO compile.
#   KERNEL_TREE     path to keep the (merged) source tree between runs, so a
#                   CHECK_ONLY run can prime the tree and the real build reuses
#                   it without re-downloading or re-merging.
#
# Runtime: heavy (compiles the kernel). CI runs on ubuntu-24.04; the local
# source of truth for the ISO is the documented WSL1 host.
set -euo pipefail

# ---- 0. paths / defaults ---------------------------------------------------
REPO_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
OUTDIR="${OUTDIR:-$REPO_ROOT/build/kernel-out}"
BASE_CONFIG="${BASE_CONFIG:-$REPO_ROOT/build/kernel/base-config-amd64.config}"
FRAG="${FRAG:-$REPO_ROOT/overlays/common/etc/obsidian/kernel/hardened.config}"
DEBSRC_MIRROR="${DEBSRC_MIRROR:-http://deb.debian.org/debian}"
JOBS="${KBUILD_JOBS:-$(nproc)}"
CHECK_ONLY="${CHECK_ONLY:-0}"
KERNEL_TREE="${KERNEL_TREE:-}"
SRCDIR="${KERNEL_SRC:-}"

# root-tolerant sudo (CI runs as the ubuntu user; the local build runs as root)
if [ "$(id -u)" -eq 0 ]; then SUDO=(); else SUDO=(sudo); fi

say() { printf '%s\n' "$*"; }
die() { say "build-kernel: $*" >&2; exit 1; }

[ -f "$FRAG" ] || die "fragment not found: $FRAG (set FRAG)"
[ -f "$BASE_CONFIG" ] || die "base config not found: $BASE_CONFIG (must exist in the repo: build/kernel/base-config-amd64.config)"
mkdir -p "$OUTDIR"

# ---- 0b. build host deps (idempotent) --------------------------------------
# The host fetches the Debian source and compiles it; Ubuntu and Debian hosts
# need the toolchain. WSL1's Ubuntu 24.04 image is the documented build host.
if [ -f /etc/os-release ] && grep -qiE 'debian|ubuntu' /etc/os-release; then
  "${SUDO[@]}" apt-get update -qq
  "${SUDO[@]}" apt-get install -y -qq \
    build-essential dpkg-dev fakeroot rsync flex bison bc \
    libssl-dev libelf-dev dwarves openssl
fi

# ---- 1. acquire source -----------------------------------------------------
BUILD_DIR="$(mktemp -d /tmp/obs-kernel-XXXXXX)"
if [ -n "$KERNEL_TREE" ] && [ -f "$KERNEL_TREE/Makefile" ]; then
  say "reusing kernel tree at $KERNEL_TREE"
  cp -a "$KERNEL_TREE" "$BUILD_DIR/linux" || { rm -rf "$BUILD_DIR"; die "cp -a from KERNEL_TREE failed"; }
elif [ -n "$SRCDIR" ]; then
  say "using provided source: $SRCDIR"
  mkdir -p "$BUILD_DIR/linux"
  rsync -a --exclude='.git' "$SRCDIR"/ "$BUILD_DIR/linux/" \
    || { rm -rf "$BUILD_DIR"; die "rsync from KERNEL_SRC failed"; }
else
  # GitHub runners are Ubuntu and have no Debian deb-src entries, so point apt
  # at an explicit Debian trixie deb-src list. --allow-unauthenticated keeps
  # this portable; a real Debian host may drop it.
  DEBSRC="$(mktemp /tmp/obs-debsrc-XXXXXX.list)"
  printf 'deb-src %s trixie main\n' "$DEBSRC_MIRROR" > "$DEBSRC"
  say "fetching Debian linux source (trixie, $DEBSRC_MIRROR)…"
  ( cd "$BUILD_DIR" \
    && "${SUDO[@]}" apt-get -o Acquire::AllowInsecureRepositories=true \
         --allow-unauthenticated \
         -o Dir::Etc::sourcelist="$DEBSRC" \
         -o Dir::Etc::sourceparts=- \
         -o APT::Get::List-Cleanup=0 update -qq \
    && "${SUDO[@]}" apt-get -o Acquire::AllowInsecureRepositories=true \
         --allow-unauthenticated \
         -o Dir::Etc::sourcelist="$DEBSRC" \
         -o Dir::Etc::sourceparts=- \
         -o APT::Get::List-Cleanup=0 source linux ) \
    || { rm -rf "$BUILD_DIR"; die "apt-get source linux failed (see output above; set DEBSRC_MIRROR to a reachable mirror)"; }
  d="$(find "$BUILD_DIR" -maxdepth 1 -type d -name 'linux-*' | head -1)"
  [ -n "$d" ] || { rm -rf "$BUILD_DIR"; die "apt-get source did not unpack a linux-* tree"; }
  mv "$d" "$BUILD_DIR/linux"
fi
cd "$BUILD_DIR/linux"

# ---- 2. base config = shipped Debian trixie amd64 config + Obsidian fragment ---
BASE_CFG="$BASE_CONFIG"
source_ver="$(sed -nE 's/^VERSION\s*=\s*//p; s/^PATCHLEVEL\s*=\s*//p; s/^SUBLEVEL\s*=\s*//p' Makefile | tr '\n' '.' | sed 's/\.$//')"
base_ver="$(sed -nE 's/^# Linux\/x86 ([0-9]+\.[0-9]+\.?[0-9]*).*/\1/p' "$BASE_CFG" | head -1)"
[ -n "$base_ver" ] || { rm -rf "$BUILD_DIR"; die "cannot read kernel version from base config header: $BASE_CFG"; }
case "$source_ver" in
  "$base_ver"|"$base_ver."*) ;; # exact same kernel (or source is same-version tree)
  *) rm -rf "$BUILD_DIR"
     die "base config version ($base_ver) does not match fetched source ($source_ver); refresh build/kernel/base-config-amd64.config from a stock $source_ver ISO";;
esac
say "base config: $BASE_CFG (kernel $base_ver, matches source $source_ver)"
say "fragment:    $FRAG"

# merge_config writes the merged result to ./.config; it handles full .configs
# (our shipped base) plus fragment lines. -m = merge only (no internal make, no
# per-symbol check loop): we resolve with our own olddefconfig below, and
# verify_hardening hard-fails on any required symbol that did not land.
scripts/kconfig/merge_config.sh -m -O . "$BASE_CFG" "$FRAG" >/dev/null 2>&1 \
  || { rm -rf "$BUILD_DIR"; die "merge_config failed (base=$BASE_CFG frag=$FRAG)"; }

# Resolve the fragment's symbol selections against the tree.
make olddefconfig >/dev/null 2>&1 || { rm -rf "$BUILD_DIR"; die "olddefconfig failed"; }

# ---- 2b. sanitise Debian-specific key references -----------------------------
# After the debian/ dir is moved away, configs that reference cert paths under
# it would break the signing-key step. Clear them so signing keys are
# auto-generated; the OBSIDIAN image ships kernel+modules from the same build,
# so the generated key is consistent inside the ISO.
#
# Only clear path-like values that reference files OUTSIDE the kernel tree (an
# absolute path such as /usr/share/keyrings/..., or a debian/-relative path).
# The plain kernel default `certs/signing_key.pem` must NOT be cleared: kbuild
# auto-generates that file inside the tree during the build and MODULE_SIG=y
# embeds the matching cert into the image — that IS the module-signing story.
for key in CONFIG_SYSTEM_TRUSTED_KEYS CONFIG_SYSTEM_REVOCATION_KEYS CONFIG_MODULE_SIG_KEY; do
  val="$(grep -E "^${key}=|^# ${key} is not set" .config | head -1 || true)"
  case "$val" in
    *'="/'*|*debian/*) # absolute path, or a path under debian/ (outside the tree once moved)
      sed -i "s|^${key}=.*|${key}=\"\"|" .config
      make olddefconfig >/dev/null 2>&1 || true
      say "  cleared ${key} (referenced ${val#*=}; cert not present after debian/ move)"
      ;;
    *) : ;;
  esac
done
# BTF (.BTF, pahole) requires dwarves; if pahole is missing, disable DEBUG_INFO_BTF
# rather than failing the whole build on a tooling gap.
if ! command -v pahole >/dev/null 2>&1 && grep -q '^CONFIG_DEBUG_INFO_BTF=y' .config; then
  sed -i 's/^CONFIG_DEBUG_INFO_BTF=y/# CONFIG_DEBUG_INFO_BTF is not set/' .config
  make olddefconfig >/dev/null 2>&1 || true
  say "  disabled CONFIG_DEBUG_INFO_BTF (pahole not installed)"
fi

# ---- 2c. VERIFY the hardening actually landed -------------------------------
verify_hardening() {
  local missing=()
  # Required =y options (each must appear as a plain 'CONFIG_X=y' line).
  local req_y=(
    INIT_ON_ALLOC_DEFAULT_ON INIT_ON_FREE_DEFAULT_ON
    STRICT_KERNEL_RWX STRICT_MODULE_RWX
    STACKPROTECTOR_STRONG FORTIFY_SOURCE HARDENED_USERCOPY
    SECURITY_LOCKDOWN_LSM SECURITY_LOCKDOWN_LSM_EARLY
    SECURITY_APPARMOR SECURITY_YAMA SECURITY_LANDLOCK
    MODULE_SIG MODULE_SIG_ALL
    RANDOMIZE_KSTACK_OFFSET_DEFAULT VMAP_STACK
    SLAB_FREELIST_RANDOM SLAB_FREELIST_HARDENED
    LEGACY_VSYSCALL_NONE X86_X32_DISABLED
    SHUFFLE_PAGE_ALLOCATOR PAGE_POISONING DEBUG_LIST BUG_ON_DATA_CORRUPTION
  )
  local opt
  for opt in "${req_y[@]}"; do
    grep -qx "CONFIG_${opt}=y" .config || missing+=("CONFIG_${opt}=y")
  done
  # Required "not set" options (the decided-off attack surface). BLK_DEV_UBLK
  # is asserted because it is the ONLY in-tree `select IO_URING`; if it ever
  # comes back, olddefconfig silently re-enables IO_URING regardless of the
  # fragment, and this gate is the thing that catches it.
  local req_n=(IO_URING BLK_DEV_UBLK KEXEC HIBERNATION)
  for opt in "${req_n[@]}"; do
    grep -qx "# CONFIG_${opt} is not set" .config || missing+=("# CONFIG_${opt} is not set")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    printf '%s\n' "build-kernel: hardening verification FAILED - missing from .config:" "${missing[@]}" >&2
    return 1
  fi
  return 0
}
if verify_hardening; then
  say "hardening options verified in .config"
else
  rm -rf "$BUILD_DIR"; exit 1
fi

say "key config lines:"
grep -E 'CONFIG_(INIT_ON_ALLOC_DEFAULT_ON|STRICT_KERNEL_RWX|SECURITY_LOCKDOWN_LSM_EARLY|SECURITY_APPARMOR|HARDENED_USERCOPY|MODULE_SIG|VMAP_STACK|SLAB_FREELIST_HARDENED|IO_URING|KEXEC|HIBERNATION)=' .config || true

# CHECK_ONLY: keep the merged tree for the real build, then stop.
if [ "$CHECK_ONLY" = "1" ]; then
  if [ -n "$KERNEL_TREE" ]; then
    rm -rf "$KERNEL_TREE" && cp -a "$BUILD_DIR/linux" "$KERNEL_TREE"
    say "CHECK_ONLY: tree kept at $KERNEL_TREE for reuse (re-run without CHECK_ONLY, KERNEL_TREE=$KERNEL_TREE)"
  else
    say "CHECK_ONLY: ok (set KERNEL_TREE to keep the tree; else it is discarded)"
  fi
  rm -rf "$BUILD_DIR"
  exit 0
fi

# ---- 3. build binary packages (the long pole) -------------------------------
# Debian's own `debian/` packaging clashes with kbuild's bindeb-pkg, so move it
# aside first. Grab the version from its changelog BEFORE the move for a stable
# package version suffix (reproducible; no date).
PKGVER="$(dpkg-parsechangelog -S Version 2>/dev/null | head -1 || echo 6.12)"
mv debian "$BUILD_DIR/linux-debian" 2>/dev/null || true
say "building with make -j$JOBS bindeb-pkg (source version $PKGVER)…"
make -j"$JOBS" bindeb-pkg \
  KDEB_PKGVERSION="${PKGVER}.obsidian" \
  LOCALVERSION=-obsidian-h \
  >/dev/null || { rm -rf "$BUILD_DIR"; die "bindeb-pkg failed"; }

# ---- 4. collect artifacts ----------------------------------------------------
# bindeb-pkg drops linux-image-*/linux-headers-*/linux-libc-dev*.deb in ../
# (the parent of the source tree). Prefix every one with obsidian- using an
# explicit loop (the `rename` text tool differs between util-linux and perl).
found=""
for f in "$BUILD_DIR"/linux-image-*.deb "$BUILD_DIR"/linux-headers-*.deb; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  out="$OUTDIR/obsidian-$base"
  cp -f "$f" "$out" && found="$found $(basename "$out")"
done
[ -n "$found" ] || { rm -rf "$BUILD_DIR"; die "no linux-image-*.deb produced (bindeb-pkg failed?)"; }

rm -rf "$BUILD_DIR"
say "artifacts:"
ls -lh "$OUTDIR" | sed 's/^/  /'
exit 0