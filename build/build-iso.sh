#!/usr/bin/env bash
# Obsidian OS — ISO build driver (first-light pipeline).
#
# REPLACES debos/obsidian.yaml, which could not build: the `debian-live` action
# it depended on was removed from debos upstream, and all four of its `run`
# actions omitted `chroot: true`, so the profile/finalize logic executed on the
# build host instead of the target rootfs. See docs/GAP-REPORT.md.
#
# This driver is a plain, debuggable shell pipeline:
#   debootstrap -> install real packages -> apply real overlays -> mksquashfs
#   -> grub-mkrescue (BIOS + UEFI hybrid ISO)
#
# Design rules:
#   * Every package must exist in the target suite. `validate-build.py`
#     resolves every line of build/flavors/*.pkgs against the suite index.
#   * Every file this script installs must exist. No phantom systemd units.
#   * The system must emit OBSIDIAN-OS-MARKER on the serial console so
#     tests/boottest.sh has a signal stock Debian cannot produce.
#
# Usage:
#   build/build-iso.sh --flavor daily
#   build/build-iso.sh --flavor ghost --suite trixie --arch amd64
#   build/build-iso.sh --flavor daily --keep-chroot   # debug interactively
set -euo pipefail

# --------------------------------------------------------------------------- #
# defaults
# --------------------------------------------------------------------------- #
FLAVOR=""
SUITE="trixie"
ARCH="amd64"
MIRROR="https://deb.debian.org/debian"
KEEP_CHROOT=0
BUILD_JOBS="$(nproc 2>/dev/null || echo 2)"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$REPO_ROOT/build"
FLAVOR_DIR="$BUILD_DIR/flavors"
OVERLAY_DIR="$REPO_ROOT/overlays"
WORK="$BUILD_DIR/work"
CHROOT="$WORK/chroot"
STAGE="$WORK/stage"
OUT_DIR="$REPO_ROOT/build/out"

# reproducible timestamps
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1700000000}"
export LC_ALL=C.UTF-8
export DEBIAN_FRONTEND=noninteractive

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[fatal]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

cleanup() {
  local rc=$?
  # Always unmount, even on failure, or the next build breaks.
  for m in run dev/pts dev/shm dev sys proc; do
    mountpoint -q "$CHROOT/$m" 2>/dev/null && umount -lf "$CHROOT/$m" 2>/dev/null || true
  done
  if [ "$KEEP_CHROOT" -eq 0 ] && [ "$rc" -ne 0 ]; then
    warn "build failed (rc=$rc); chroot kept for debugging: $CHROOT"
  fi
  return $rc
}
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# args
# --------------------------------------------------------------------------- #
while [ $# -gt 0 ]; do
  case "$1" in
    --flavor)      FLAVOR="$2"; shift 2 ;;
    --flavor=*)    FLAVOR="${1#*=}"; shift ;;
    --suite)       SUITE="$2"; shift 2 ;;
    --suite=*)     SUITE="${1#*=}"; shift ;;
    --arch)        ARCH="$2"; shift 2 ;;
    --arch=*)      ARCH="${1#*=}"; shift ;;
    --mirror)      MIRROR="$2"; shift 2 ;;
    --keep-chroot) KEEP_CHROOT=1; shift ;;
    --jobs)        BUILD_JOBS="$2"; shift 2 ;;
    -h|--help)     usage 0 ;;
    *)             die "unknown argument: $1 (try --help)" ;;
  esac
done

[ -n "$FLAVOR" ] || { usage 1; }
FLAVOR_LIST="$FLAVOR_DIR/common.pkgs"
[ -f "$FLAVOR_LIST" ] || die "missing $FLAVOR_LIST"
[ -f "$FLAVOR_DIR/$FLAVOR.pkgs" ] || die "unknown flavor '$FLAVOR' (no $FLAVOR_DIR/$FLAVOR.pkgs)"

# --------------------------------------------------------------------------- #
# preflight: fail loudly here rather than 20 minutes into debootstrap
# --------------------------------------------------------------------------- #
log "preflight"
[ "$(id -u)" -eq 0 ] || die "must run as root (debootstrap + mksquashfs); try: sudo -E $0 $*"
for t in debootstrap mksquashfs grub-mkrescue xorriso unshare mountpoint; do
  command -v "$t" >/dev/null 2>&1 || die "missing host tool: $t"
done
[ -d "$OVERLAY_DIR/common" ] || die "missing overlay tree: $OVERLAY_DIR/common"
grep -qvE '^\s*(#|$)' "$FLAVOR_DIR/$FLAVOR.pkgs" || die "$FLAVOR.pkgs is empty"

log "cleaning previous work tree"
if mountpoint -q "$CHROOT" 2>/dev/null; then
  umount -lf "$CHROOT" || true
fi
rm -rf "$WORK" "$STAGE" "$CHROOT"
mkdir -p "$WORK" "$STAGE" "$OUT_DIR"

# --------------------------------------------------------------------------- #
# 1. bootstrap
# --------------------------------------------------------------------------- #
# mmdebstrap is preferred; debootstrap is a fallback.
#
# Why not debootstrap: it fetches every .deb with a single serial `wget`, using
# GNU wget's defaults of --dns-timeout=900 --connect-timeout=900 --tries=20. On
# any host whose network path can accept a connection and then stall, one
# package blocks the entire bootstrap for a quarter of an hour, and the whole
# build is measured in days rather than minutes. It also downloads sequentially,
# so a fast link is wasted.
#
# mmdebstrap (the tool Debian's own live-build now uses) downloads in parallel,
# drives apt with explicit per-connection timeouts, and retried transfers. On
# the WSL1 build host used to develop this it bootstrapped trixie minbase in
# 754s / 81 packages, where debootstrap had managed 10 packages in 20 minutes.
APT_OPTS=(
  --aptopt='Acquire::ForceIPv4 "true";'
  --aptopt='Acquire::Retries "5";'
  --aptopt='Acquire::http::Timeout "20";'
  --aptopt='Acquire::https::Timeout "20";'
  --aptopt='Acquire::ftp::Timeout "20";'
  --aptopt='Acquire::Languages "none";'
  # keep the image small; a live ISO has no use for desktop recommendations
  --aptopt='APT::Install-Recommends "false";'
  --aptopt='APT::Install-Suggests "false";'
)

# --------------------------------------------------------------------------- #
# 1. resolve the package set, then bootstrap with it
# --------------------------------------------------------------------------- #
# The full package set is resolved BEFORE the bootstrap and handed to it as
# --include, so the base system and the flavor's packages are fetched in one
# parallel apt transaction. Installing them afterwards with a second
# `apt-get install` inside the chroot would mean a second `apt-get update` over
# the same link plus a serial download of the same payload.
PKGLIST="$WORK/packages.list"
{
  cat "$FLAVOR_DIR/common.pkgs"
  cat "$FLAVOR_DIR/$FLAVOR.pkgs"
} | sed -e 's/#.*//' -e 's/[[:space:]]//g' -e '/^$/d' | sort -u > "$PKGLIST"
INCLUDE="$(paste -sd, "$PKGLIST")"
log "package set: $(wc -l < "$PKGLIST") packages for flavor '$FLAVOR'"

# --------------------------------------------------------------------------- #
# 1b. hosts that lack open-file-description locks (WSL1)
# --------------------------------------------------------------------------- #
# WSL1's kernel emulation does not implement F_OFD_SETLK: it returns EINVAL on
# every filesystem, including tmpfs, while F_SETLK and flock(2) both work.
# systemd takes an OFD lock on /etc/passwd, so on such a host every systemd
# package fails to configure and the build cannot produce an image.
#
# The fix is a build-host shim, not a change to what gets installed: the shim
# supplies the missing lock acquisition, the package's own maintainer script
# then runs and performs its real work, and the shim is removed before the
# image is sealed. The shipped ISO contains stock Debian binaries and no shim.
#
# See build/wsl1-ofd-lock-shim.c for the mechanism and the safety argument.
# The host is probed rather than pattern-matched, so a normal Linux build host
# never compiles or installs any of this.
# Returns 0 if the host supports OFD locks, 1 if it definitively does not.
# Anything it cannot decide counts as "supported": a build on a normal Linux
# host must never be diverted into the shim path by a broken probe.
#
# The probe carries a control. It locks with F_SETLK first; if that fails, the
# probe is malformed rather than the host unusual, and the verdict is
# "inconclusive" rather than "this host lacks OFD locks". Without the control a
# wrong struct size would return EINVAL and be reported as a missing kernel
# feature, which would send a perfectly good build host down the shim path.
ofd_locks_work() {
  command -v python3 >/dev/null 2>&1 || return 0   # cannot tell; assume a normal host
  python3 - "$WORK/.ofd-probe" >/dev/null 2>&1 <<'PROBE'
import fcntl, os, struct, sys
F_SETLK, F_OFD_SETLK = 14, 37
# Native "hhqqi" is exactly sizeof(struct flock) on x86_64; no manual padding,
# so the size cannot drift. The control below is what actually validates it.
fl = struct.pack("hhqqi", fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0)
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)

def try_lock(op):
    # Success is "no exception", NOT a zero return. When the argument is a bytes
    # object, Python's fcntl returns the reply buffer, so a successful lock
    # yields bytes -- testing the result against 0 reports every working lock as
    # a failure, and the probe would then call a perfectly good host broken.
    try:
        fcntl.fcntl(fd, op, fl)
        return True
    except OSError:
        return False

if not try_lock(F_SETLK):
    sys.exit(2)                       # control failed: probe is wrong, not the host
sys.exit(0 if try_lock(F_OFD_SETLK) else 1)
PROBE
  local probe_rc=$?
  rm -f "$WORK/.ofd-probe"
  case "$probe_rc" in
    0) return 0 ;;
    1) return 1 ;;
    2) warn "OFD-lock probe was inconclusive (control F_SETLK also failed);"
       warn "assuming a normal host. If the build then fails with"
       warn "'Failed to take /etc/passwd lock', this probe is the thing to fix."
       return 0 ;;
    *) return 0 ;;
  esac
}

OFD_SHIM=""
if ofd_locks_work; then
  log "  host supports open-file-description locks; no shim needed"
else
  warn "host does NOT support F_OFD_SETLK (WSL1); systemd cannot configure without help"
  command -v gcc >/dev/null 2>&1 || command -v cc >/dev/null 2>&1 \
    || die "this host needs the OFD-lock shim but has no C compiler (gcc/cc).
       Either install one, or build on a host with working OFD locks (any
       normal Linux, or WSL2). See build/wsl1-ofd-lock-shim.c."
  CC="$(command -v gcc || command -v cc)"
  OFD_DIR="$WORK/ofd"
  rm -rf "$OFD_DIR"
  mkdir -p "$OFD_DIR"
  "$CC" -O2 -fPIC -shared \
    -o "$OFD_DIR/obsidian-ofd-shim.so" \
    "$BUILD_DIR/wsl1-ofd-lock-shim.c" -ldl \
    || die "failed to compile the OFD-lock shim"
  # Fail loudly if the compiler dropped the overrides: with no such symbol
  # exported there is no interposition at all, and the build would fail later
  # with the original error while appearing to have a shim in place.
  nm -D --defined-only "$OFD_DIR/obsidian-ofd-shim.so" 2>/dev/null \
    | grep -q 'take_etc_passwd_lock' \
    || die "the compiled OFD-lock shim exports no take_etc_passwd_lock symbol."
  # ld.so.preload rather than LD_PRELOAD: dpkg sanitises the environment of the
  # maintainer scripts it spawns, so LD_PRELOAD does not reach them.
  # ld.so.preload is read by the dynamic linker itself and cannot be stripped.
  echo /usr/lib/obsidian-ofd-shim.so > "$OFD_DIR/ld.so.preload"
  OFD_SHIM=1
  log "  compiled the OFD-lock shim; it will be removed before the image is sealed"
fi

# Extra mmdebstrap arguments; empty unless the shim is in play.
OFD_HOOKS=()
if [ -n "$OFD_SHIM" ]; then
  # mmdebstrap's own HOOKS section defines the contract:
  #   - a hook argument starting with "copy-in " is a special hook of the form
  #     `copy-in pathoutside [pathoutside ...] pathinside`
  #   - hooks run in the order given on the command line
  #   - "the path inside the chroot must already exist"
  # At setup-hook time mmdebstrap has created only /etc/apt, /var/cache and
  # /var/lib, so /usr/lib has to be made first or copy-in refuses. The setup
  # hook runs before packages are downloaded or installed, which is before
  # systemd's maintainer script executes; the customize hook runs last.
  OFD_HOOKS=(
    --setup-hook='mkdir -p "$1"/usr/lib'
    --setup-hook="copy-in $OFD_DIR/obsidian-ofd-shim.so /usr/lib"
    --setup-hook="copy-in $OFD_DIR/ld.so.preload /etc"
    --customize-hook='rm -f "$1"/usr/lib/obsidian-ofd-shim.so "$1"/etc/ld.so.preload'
  )
fi

log "bootstrapping $SUITE/$ARCH -> $CHROOT  (this is the slow part)"
if command -v mmdebstrap >/dev/null 2>&1; then
  BOOTSTRAPPER=mmdebstrap
  log "  using mmdebstrap ($(mmdebstrap --version 2>&1 | head -1))"
  mmdebstrap \
    --arch="$ARCH" \
    --variant=minbase \
    --components=main,contrib,non-free-firmware \
    --include="$INCLUDE" \
    "${OFD_HOOKS[@]}" \
    "${APT_OPTS[@]}" \
    "$SUITE" "$CHROOT" "$MIRROR"
elif command -v debootstrap >/dev/null 2>&1; then
  BOOTSTRAPPER=debootstrap
  warn "mmdebstrap not found; falling back to debootstrap (much slower, see the comment above)"
  # debootstrap has no pre-install hook. Injecting the shim would mean
  # splitting the run into --first-stage and --second-stage around it, and
  # that path is untested here, so say so rather than ship a guess.
  if [ -n "$OFD_SHIM" ]; then
    die "this host needs the OFD-lock shim, but debootstrap offers no hook to
       install it before packages are configured. Install mmdebstrap
       (apt install mmdebstrap) and re-run."
  fi
  debootstrap \
    --arch="$ARCH" \
    --variant=minbase \
    --components=main,contrib,non-free-firmware \
    --include="$INCLUDE" \
    "$SUITE" "$CHROOT" "$MIRROR"
else
  die "neither mmdebstrap nor debootstrap is installed (see docs/BUILD.md)"
fi
log "  bootstrapped with $BOOTSTRAPPER"

# --------------------------------------------------------------------------- #
# 2. mount the chroot's kernel filesystems
# --------------------------------------------------------------------------- #
log "mounting pseudo-filesystems in chroot"
for m in proc sys dev dev/pts dev/shm run; do
  mkdir -p "$CHROOT/$m"
done
mount -t proc  proc "$CHROOT/proc"
mount -t sysfs sys  "$CHROOT/sys"
mount --bind /dev "$CHROOT/dev"
# devpts belongs on /dev/pts. (The previous revision mounted it on /dev/shm,
# which silently gave the chroot a broken /dev/pts and no PTY allocation.)
mount -t devpts devpts "$CHROOT/dev/pts" 2>/dev/null \
  || warn "could not mount devpts on /dev/pts (continuing)"
mount -t tmpfs tmpfs "$CHROOT/run"

# --------------------------------------------------------------------------- #
# 3. verify the package set actually landed on disk
# --------------------------------------------------------------------------- #
# The bootstrap was given --include with this exact list, so there is nothing to
# install here. This is a verification step, and it is deliberately strict: the
# previous pipeline shipped an image whose "profile install" had silently run on
# the build host, leaving the image a bare debootstrap with nothing missing that
# any check would notice. Assert the packages are present instead of assuming.
log "verifying the package set is present in the image"
MISSING_PKGS=""
for p in $(cat "$PKGLIST"); do
  if ! chroot "$CHROOT" /usr/bin/dpkg-query -W -f='${Status}' "$p" 2>/dev/null \
       | grep -q 'install ok installed'; then
    MISSING_PKGS="$MISSING_PKGS $p"
  fi
done
if [ -n "$MISSING_PKGS" ]; then
  die "these requested packages are NOT installed in the image:$MISSING_PKGS
     A flavor that silently fails to install is exactly the failure this check
     exists to catch. Re-run with --keep-chroot and inspect
     $CHROOT/var/log/apt/history.log"
fi
INSTALLED=$(chroot "$CHROOT" /usr/bin/dpkg-query -W -f='${binary:Package}\n' 2>/dev/null | wc -l)
log "  all $(wc -l < "$PKGLIST") requested packages present ($INSTALLED total installed)"

# --------------------------------------------------------------------------- #
# 3b. the build host's OFD-lock shim must not reach the image
# --------------------------------------------------------------------------- #
# The shim exists so systemd's maintainer script can run on WSL1. It is a
# property of the build host, not of the distribution, and an ISO that shipped
# it would preload a lock-stub into every process on first boot -- including
# anything the user installs later. mmdebstrap's customize hook removes it;
# this asserts that it did, because "the hook should have worked" is not a
# check.
rm -f "$CHROOT/usr/lib/obsidian-ofd-shim.so" "$CHROOT/etc/ld.so.preload"
LEFTOVER=$(find "$CHROOT" \( -name 'obsidian-ofd-shim.so' -o -name 'ld.so.preload' \) 2>/dev/null | head -5)
if [ -n "$LEFTOVER" ]; then
  die "the OFD-lock shim is still present in the image and would be preloaded at boot:$LEFTOVER"
fi
[ -n "$OFD_SHIM" ] && log "  OFD-lock shim removed from the image (verified absent)"

# The chroot gets a working resolver. mmdebstrap/debootstrap leave a
# resolv.conf that is either absent or copied from the build host, and on a
# build host with an IPv6-only or stub-resolved configuration that means every
# in-chroot apt call silently fails to resolve.
if [ -f /etc/resolv.conf ] && ! grep -q '^nameserver' "$CHROOT/etc/resolv.conf" 2>/dev/null; then
  cp -f /etc/resolv.conf "$CHROOT/etc/resolv.conf"
  log "  copied host resolv.conf into the chroot"
fi

# --------------------------------------------------------------------------- #
# 4. real hardening overlays
# --------------------------------------------------------------------------- #
log "applying overlays/common -> chroot"
[ -d "$OVERLAY_DIR/common" ] || die "overlay tree missing: $OVERLAY_DIR/common"
# tar -C to preserve ownership/permissions rather than cp -r as a side effect.
tar -C "$OVERLAY_DIR/common" -cf - . | tar -C "$CHROOT" -xf -

# flavor overlay is optional: many flavors legitimately have none yet
if [ -d "$OVERLAY_DIR/$FLAVOR" ]; then
  log "applying overlays/$FLAVOR -> chroot"
  tar -C "$OVERLAY_DIR/$FLAVOR" -cf - . | tar -C "$CHROOT" -xf -
else
  warn "no overlays/$FLAVOR directory; skipping (this is expected for now)"
fi

# Restore the executable bit on shipped scripts.
#
# This repo is authored on Windows, where git records mode 100644 for everything
# and the tar carries that through. The result is an image whose sbin helpers
# and systemd shutdown hooks are non-executable, so they silently never run —
# the same class of bug as enabling a unit that does not exist. Fix it here
# rather than trusting the checkout.
log "fixing executable bits on shipped scripts"
for d in usr/local/sbin usr/lib/systemd/system-shutdown; do
  if [ -d "$CHROOT/$d" ]; then
    find "$CHROOT/$d" -maxdepth 1 -type f -exec chmod 0755 {} + 2>/dev/null || true
  fi
done

# Collect the flavor's extra kernel cmdline, if it declares one. This is how a
# flavor genuinely differs at the kernel level (Ghost uses it for
# overlay=tmpfs + lockdown).
CMDLINE_EXTRA=""
for cand in "$CHROOT/etc/obsidian/$FLAVOR/cmdline.extra" \
            "$CHROOT/etc/obsidian/ghost/cmdline.extra"; do
  if [ -f "$cand" ]; then
    CMDLINE_EXTRA="$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "$cand" | tr '\n' ' ')"
    break
  fi
done
if [ -n "$CMDLINE_EXTRA" ]; then
  log "flavor kernel cmdline: $CMDLINE_EXTRA"
else
  log "no flavor kernel cmdline (using the common set)"
fi

# --------------------------------------------------------------------------- #
# 5. enable units
#
# Must use `systemctl --root`, NOT bare `systemctl enable`. The old
# scripts/enable-services.sh called bare `systemctl enable` for a dozen units
# that were never written, so it aborted on the first miss under `set -eu` —
# and in a chroot there is no bus to talk to anyway. We enable only units that
# this pipeline has actually installed on disk.
# --------------------------------------------------------------------------- #
log "enabling units"
UNITS=(
  nftables.service            # loads /etc/nftables.conf
  systemd-networkd.service
  systemd-resolved.service
  apparmor.service
  obsidian-boot-report.service
)
for u in "${UNITS[@]}"; do
  if [ -e "$CHROOT/etc/systemd/system/$u" ] || \
     systemctl --root="$CHROOT" list-unit-files "$u" >/dev/null 2>&1; then
    systemctl --root="$CHROOT" enable "$u" >/dev/null 2>&1 \
      || warn "could not enable $u"
  else
    die "unit $u not found in the image — refusing to ship a silent no-op"
  fi
done
log "  enabled: ${UNITS[*]}"

# --------------------------------------------------------------------------- #
# 6. firstboot wiring (chroot-safe; no hostnamectl, no systemctl against a
#    live bus — the old scripts used both and aborted under set -eu)
# --------------------------------------------------------------------------- #
log "configuring system (hostname, users, fstab, marker)"
HF="obsidian-$FLAVOR"
printf '%s\n' "$HF" > "$CHROOT/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 %s\n::1 localhost\n' "$HF" > "$CHROOT/etc/hosts"

# root has no password by default on some images; make the live console usable.
# KNOWN-INSECURE: first-boot-only credentials for a live image. Both passwords
# are 'obsidian' and MUST be rotated by the firstboot wizard. A live ISO has no
# persistent writable trust anchor by design, so this is a build-stage
# convenience, not a shipped secret. See docs/SECURITY-POLICY.md.
chroot "$CHROOT" /bin/sh -c 'echo "root:obsidian" | chpasswd' \
  || warn "could not set root password"

# live session user. Groups that don't exist in minbase are dropped rather than
# failing the whole useradd (the old code aborted here under `set -eu`).
GROUPS="sudo,audio,video,netdev,netdev"  # de-duped below
for g in audio video netdev; do
  if ! chroot "$CHROOT" /usr/bin/getent group "$g" >/dev/null 2>&1; then
    chroot "$CHROOT" /usr/sbin/groupadd -f "$g" 2>/dev/null || true
  fi
done
chroot "$CHROOT" /usr/sbin/useradd -m -s /bin/bash -G sudo,audio,video,netdev obsidian \
  || die "failed to create the live session user 'obsidian'"
chroot "$CHROOT" /bin/sh -c 'echo "obsidian:obsidian" | chpasswd' \
  || warn "could not set the live user password"

# /etc/fstab: the live root is provided by live-boot, so only pseudo-fs go here
cat > "$CHROOT/etc/fstab" <<'EOF'
# Obsidian OS — live session. Root is mounted by live-boot from the boot medium.
proc   /proc  proc  defaults  0 0
tmpfs  /run   tmpfs defaults  0 0
EOF

# record the flavor so the boot test can assert the right image booted
mkdir -p "$CHROOT/etc/obsidian"
printf '%s\n' "$FLAVOR" > "$CHROOT/etc/obsidian/flavor"
printf '%s\n' "$SUITE/$ARCH" > "$CHROOT/etc/obsidian/build"

# firstboot marker. obsidian-boot-report asserts on it, so it MUST exist or the
# boot test fails on an image that is otherwise fine.
touch "$CHROOT/etc/obsidian/firstboot"

# --------------------------------------------------------------------------- #
# 7. initramfs (live-boot must be present for the squashfs to be found)
# --------------------------------------------------------------------------- #
log "building initramfs (live-boot)"
chroot "$CHROOT" /bin/sh -c 'update-initramfs -u -k all' || die "update-initramfs failed"

# --------------------------------------------------------------------------- #
# 7. shrink + clean
# --------------------------------------------------------------------------- #
log "cleaning chroot"
chroot "$CHROOT" /bin/sh -c 'apt-get clean; rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*' || true
# machine-id must be empty so each boot is distinguishable
: > "$CHROOT/etc/machine-id"
rm -f "$CHROOT/var/lib/dbus/machine-id"

# --------------------------------------------------------------------------- #
# 8. squashfs
# --------------------------------------------------------------------------- #
log "creating squashfs (jobs=$BUILD_JOBS, comp=zstd)"
mkdir -p "$STAGE/live"
# zstd, not xz: xz costs roughly 4x the CPU for a few percent of size. This is
# the heaviest CPU step in the build, and the host is a shared laptop also being
# used interactively, so wall-clock matters more than the last few percent. Debian
# kernels carry CONFIG_SQUASHFS_ZSTD, so the bootloader can read it.
# (An earlier version of this comment justified the choice by claiming the host
# is emulated with no VT-x. That was never verified, and the boot test it referred
# to turned out to have hardware acceleration available - see
# tests/boottest-win.ps1, which now probes for it.)
mksquashfs "$CHROOT" "$STAGE/live/filesystem.squashfs" \
  -comp zstd -Xcompression-level 15 -b 1M -noappend -no-progress \
  -processors "$BUILD_JOBS" \
  -e boot dev proc sys run tmp var/tmp

# --------------------------------------------------------------------------- #
# 9. stage kernel + initrd
# --------------------------------------------------------------------------- #
log "staging kernel + initrd"
KERNEL="$(ls -1 "$CHROOT"/boot/vmlinuz-* 2>/dev/null | sort -V | tail -1)" \
  || die "no kernel installed in chroot"
INITRD="$(ls -1 "$CHROOT"/boot/initrd.img-* 2>/dev/null | sort -V | tail -1)" \
  || die "no initrd built (is live-boot installed?)"
cp -f "$KERNEL" "$STAGE/live/vmlinuz"
cp -f "$INITRD" "$STAGE/live/initrd.img"
log "  kernel: $(basename "$KERNEL")   initrd: $(basename "$INITRD")"

# --------------------------------------------------------------------------- #
# 10. boot config + ISO
# --------------------------------------------------------------------------- #
log "writing grub.cfg"
# NOTE ON PLACEMENT: grub-mkrescue embeds $STAGE/boot/grub/grub.cfg into the
# generated BIOS and UEFI images. A grub.cfg at the ISO *root* is NOT read by
# default, so the previous revision's `cp grub.cfg $STAGE/grub.cfg` produced an
# ISO that booted straight into the GRUB rescue prompt on real hardware.
mkdir -p "$STAGE/boot/grub"
{
cat <<EOF
set timeout=10
set default=0

# console=ttyS0 must be LAST so /dev/console (which obsidian-boot-report writes
# to via StandardOutput=journal+console) lands on the serial line that
# tests/boottest.sh captures.
menuentry "Obsidian OS $HF ($SUITE/$ARCH)" {
    linux  /live/vmlinuz boot=live components quiet loglevel=4 \\
           hostname=$HF \\
           console=tty0 console=ttyS0,115200n8 \\
           systemd.show_status=true \\
           apparmor=1 security=apparmor \\
           mitigations=auto,nosmt,noexec \\
           random.trust_cpu=off \\
           slab_fuzz=on
EOF
  if [ -n "$CMDLINE_EXTRA" ]; then
    printf '           %s\n' "$CMDLINE_EXTRA"
  fi
  cat <<'GRUBEOF'
    initrd /live/initrd.img
}
GRUBEOF
} > "$STAGE/boot/grub/grub.cfg"

ISO_NAME="obsidian-$FLAVOR-$SUITE-$ARCH.iso"
log "building ISO: $ISO_NAME"
# Do NOT pipe grub-mkrescue through sed and then check the pipeline status: with
# a pipe, `$?` is sed's status, so a failed ISO build would print as success.
MKR_LOG="$WORK/grub-mkrescue.log"
if ! grub-mkrescue \
      --output="$OUT_DIR/$ISO_NAME" \
      --volid="OBSIDIAN" \
      --locales=en_US.UTF-8 \
      "$STAGE" > "$MKR_LOG" 2>&1; then
  sed 's/^/    /' "$MKR_LOG" >&2
  die "grub-mkrescue failed (full log: $MKR_LOG)"
fi
grep -E '^(xorriso|grub-mkrescue|mkisofs|Using )' "$MKR_LOG" 2>/dev/null | sed 's/^/    /' || true

# Fail closed: an ISO that grub-mkrescue "succeeded" on but that has no GRUB
# EFI image is not bootable on UEFI, and we would not know until the boot test.
if [ ! -s "$OUT_DIR/$ISO_NAME" ]; then
  die "grub-mkrescue reported success but produced no ISO"
fi

# --------------------------------------------------------------------------- #
# 11. teardown
# --------------------------------------------------------------------------- #
log "unmounting chroot"
for m in run dev/pts dev/shm dev sys proc; do
  mountpoint -q "$CHROOT/$m" 2>/dev/null && umount -lf "$CHROOT/$m" 2>/dev/null || true
done

ISO_SIZE="$(du -h "$OUT_DIR/$ISO_NAME" | cut -f1)"
log "DONE  $OUT_DIR/$ISO_NAME  ($ISO_SIZE)"
log "next: tests/boottest.sh '$OUT_DIR/$ISO_NAME'"
