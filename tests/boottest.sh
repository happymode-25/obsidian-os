#!/bin/bash
# Obsidian OS — strict QEMU boot test.
#
# Replaces the previous tests/boottest.sh, which passed on a completely broken
# image. It ran with BOOTTEST_SOFT=1 and fell back to matching
# `login:|Reached target|tty[S0-9]` — a stock Debian live ISO prints all three,
# so the gate was green no matter what the build actually did. A soft gate that
# cannot fail is worse than no gate.
#
# This version asserts only on things a stock Debian ISO cannot produce:
#   * OBSIDIAN-OS-MARKER   emitted only by our obsidian-boot-report unit
#   * OBSIDIAN-OS-READY    same
#   * OBSIDIAN-CHECK ...  per-subsystem attestation lines
#   * a hard negative:    the log must NOT contain stock-Debian fingerprints
#                         that would indicate the debian-live action silently
#                         replaced our rootfs with a vanilla one
#
# Usage: tests/boottest.sh <image.iso> [--timeout N] [--flavor F] [--keep-log]
# Exit:  0 = all required checks passed, 1 = failure (log tail printed),
#        2 = bad usage.
set -uo pipefail

ISO=""
TIMEOUT=420
FLAVOR=""
KEEP_LOG=0

while [ $# -gt 0 ]; do
  case "$1" in
    --timeout)  TIMEOUT="$2"; shift 2 ;;
    --timeout=*) TIMEOUT="${1#*=}"; shift ;;
    --flavor)   FLAVOR="$2"; shift 2 ;;
    --flavor=*) FLAVOR="${1#*=}"; shift ;;
    --keep-log) KEEP_LOG=1; shift ;;
    -h|--help)  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)         echo "boottest: unknown option $1" >&2; exit 2 ;;
    *)          if [ -z "$ISO" ]; then ISO="$1"; shift; else
                  echo "boottest: unexpected argument $1" >&2; exit 2; fi ;;
  esac
done

[ -n "$ISO" ] || { echo "usage: $0 <image.iso> [--timeout N] [--flavor F]" >&2; exit 2; }
[ -f "$ISO" ] || { echo "boottest: ISO not found: $ISO" >&2; exit 1; }
command -v qemu-system-x86_64 >/dev/null 2>&1 || {
  echo "boottest: qemu-system-x86_64 not on PATH" >&2; exit 1; }

LOG="$(mktemp "${TMPDIR:-/tmp}/obsidian-boot-XXXXXX.log")"
QPID=""

cleanup() {
  [ -n "$QPID" ] && kill "$QPID" 2>/dev/null
  sleep 1
  [ -n "$QPID" ] && kill -9 "$QPID" 2>/dev/null
  if [ "$KEEP_LOG" -eq 1 ]; then
    echo "boottest: log kept at $LOG"
  else
    rm -f "$LOG"
  fi
}
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# required markers
# --------------------------------------------------------------------------- #
REQUIRED=(
  "OBSIDIAN-OS-MARKER v1"   # proves our rootfs booted, not stock Debian
  "OBSIDIAN-OS-READY"       # the report unit ran to completion
  "OBSIDIAN-CHECK sysctl-overlay: present"
  "OBSIDIAN-CHECK apparmor:"
  "OBSIDIAN-CHECK firstboot:"
)

# Anti-regression: these are the fingerprints of the debos `debian-live`
# action bug, where the built chroot was discarded and a vanilla Debian live
# ISO was substituted. If any shows up, the image is a lie.
FORBIDDEN=(
  "Welcome to Debian"
  "Debian GNU/Linux"
)

# --------------------------------------------------------------------------- #
# boot
# --------------------------------------------------------------------------- #
echo "boottest: $ISO"
echo "  timeout=${TIMEOUT}s  required=${#REQUIRED[@]}  forbidden=${#FORBIDDEN[@]}"
if [ -n "$FLAVOR" ]; then echo "  expecting flavor: $FLAVOR"; fi

# -accel tcg: the reference host has VT-x disabled in firmware, so KVM/WHPX
# are unavailable. TCG is slow but deterministic, which is what a gate wants.
qemu-system-x86_64 \
  -m 2048 -smp 2 \
  -boot d -cdrom "$ISO" \
  -display none -accel tcg \
  -serial "file:$LOG" \
  -no-reboot \
  &
QPID=$!

# --------------------------------------------------------------------------- #
# wait for the terminal marker
# --------------------------------------------------------------------------- #
SECONDS=0
TERMINAL_SEEN=0
while [ "$SECONDS" -lt "$TIMEOUT" ]; do
  kill -0 "$QPID" 2>/dev/null || break
  if grep -qF "OBSIDIAN-OS-READY" "$LOG" 2>/dev/null; then
    TERMINAL_SEEN=1
    break
  fi
  sleep 2
done

FAIL=0

# --------------------------------------------------------------------------- #
# evaluate
# --------------------------------------------------------------------------- #
if [ "$TERMINAL_SEEN" -eq 0 ]; then
  echo "boottest: FAIL — never saw OBSIDIAN-OS-READY within ${TIMEOUT}s" >&2
  FAIL=1
else
  for m in "${REQUIRED[@]}"; do
    if grep -qF "$m" "$LOG"; then
      echo "  ok      $m"
    else
      echo "  MISSING $m" >&2
      FAIL=1
    fi
  done
  for f in "${FORBIDDEN[@]}"; do
    if grep -qF "$f" "$LOG"; then
      echo "  FORBIDDEN '$f' present — image is vanilla Debian, not Obsidian" >&2
      FAIL=1
    fi
  done
  if [ -n "$FLAVOR" ]; then
    if grep -qF "flavor=$FLAVOR" "$LOG"; then
      echo "  ok      flavor=$FLAVOR"
    else
      echo "  MISSING flavor=$FLAVOR (wrong image?)" >&2
      FAIL=1
    fi
  fi
  # report the attestation lines so CI logs show what the image thinks it is
  echo "  --- attestation ---"
  grep -o 'OBSIDIAN-CHECK[^"]*' "$LOG" 2>/dev/null | sort -u | sed 's/^/  /'
fi

if [ "$FAIL" -ne 0 ]; then
  echo "boottest: FAIL" >&2
  echo "--- last 60 lines of serial log ---" >&2
  [ -f "$LOG" ] && tail -60 "$LOG" >&2
  exit 1
fi

echo "boottest: PASS (${SECONDS}s)"
exit 0
