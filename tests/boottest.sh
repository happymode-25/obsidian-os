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
# The markers themselves live in tests/boot-markers.conf, shared with
# tests/boottest-win.ps1. See that file for why they are not inline.
#
# Usage: tests/boottest.sh <image.iso> [--timeout N] [--flavor F] [--accel A] [--keep-log]
#   --accel  auto (default) | kvm | tcg
# Exit:  0 = all required checks passed, 1 = failure (log tail printed),
#        2 = bad usage.
set -uo pipefail

ISO=""
TIMEOUT=420
FLAVOR=""
KEEP_LOG=0
ACCEL=auto

while [ $# -gt 0 ]; do
  case "$1" in
    --timeout)  TIMEOUT="$2"; shift 2 ;;
    --timeout=*) TIMEOUT="${1#*=}"; shift ;;
    --flavor)   FLAVOR="$2"; shift 2 ;;
    --flavor=*) FLAVOR="${1#*=}"; shift ;;
    --accel)    ACCEL="$2"; shift 2 ;;
    --accel=*)  ACCEL="${1#*=}"; shift ;;
    --keep-log) KEEP_LOG=1; shift ;;
    -h|--help)  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)         echo "boottest: unknown option $1" >&2; exit 2 ;;
    *)          if [ -z "$ISO" ]; then ISO="$1"; shift; else
                  echo "boottest: unexpected argument $1" >&2; exit 2; fi ;;
  esac
done

[ -n "$ISO" ] || { echo "usage: $0 <image.iso> [--timeout N] [--flavor F] [--accel A] [--keep-log]" >&2; exit 2; }
[ -f "$ISO" ] || { echo "boottest: ISO not found: $ISO" >&2; exit 1; }
command -v qemu-system-x86_64 >/dev/null 2>&1 || {
  echo "boottest: qemu-system-x86_64 not on PATH" >&2; exit 1; }
case "$ACCEL" in
  auto|kvm|tcg) ;;
  *) echo "boottest: --accel must be auto, kvm or tcg (got '$ACCEL')" >&2; exit 2 ;;
esac

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
# Read from tests/boot-markers.conf so this gate and tests/boottest-win.ps1
# cannot drift apart. A literal list here is how you end up with two different
# definitions of "passes" on two different machines.
MARKERS="$(dirname "$(readlink -f "$0")")/boot-markers.conf"
if [ ! -r "$MARKERS" ]; then
  echo "boottest: cannot read the marker list: $MARKERS" >&2
  exit 2
fi
REQUIRED=()
FORBIDDEN=()
while read -r kind marker; do
  case "$kind" in
    required)  REQUIRED+=("$marker")  ;;
    forbidden) FORBIDDEN+=("$marker") ;;
  esac
done < "$MARKERS"
if [ "${#REQUIRED[@]}" -eq 0 ]; then
  # An empty list would make every image "pass". That is the exact failure mode
  # this file was written to remove, so refuse rather than proceed.
  echo "boottest: $MARKERS lists no required markers; refusing to run a gate" \
       "that cannot fail" >&2
  exit 2
fi

# --------------------------------------------------------------------------- #
# accelerator
# --------------------------------------------------------------------------- #
# KVM is roughly an order of magnitude faster than TCG, and that is the
# difference between a boot gate you can iterate against and one that times out
# on a loaded machine. TCG is the always-correct fallback.
#
# Do not infer KVM from `[ -e /dev/kvm ]`: the device node can exist while
# ownership or group membership denies access, and inside a container it can
# exist without a hypervisor behind it. Ask QEMU instead - start a real `pc`
# machine with no boot media and no CPU execution, and see whether it survives.
# If the accelerator cannot initialise, QEMU aborts immediately. A probe
# failure must fall back to TCG, never abort the gate.
probe_accel() {
  local name="$1" pid
  qemu-system-x86_64 -accel "$name" -machine pc \
    -display none -nodefaults -S >/dev/null 2>&1 &
  pid=$!
  sleep 5
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    return 0
  fi
  wait "$pid" 2>/dev/null
  return 1
}

ACCEL_USE="$ACCEL"
if [ "$ACCEL" = auto ]; then
  if probe_accel kvm; then
    ACCEL_USE=kvm
  else
    ACCEL_USE=tcg
    echo "  accel kvm : unavailable; falling back to tcg (the boot will be slow)"
  fi
fi
echo "  accelerator: $ACCEL_USE"

# --------------------------------------------------------------------------- #
# boot
# --------------------------------------------------------------------------- #
echo "boottest: $ISO"
echo "  timeout=${TIMEOUT}s  required=${#REQUIRED[@]}  forbidden=${#FORBIDDEN[@]}"
if [ -n "$FLAVOR" ]; then echo "  expecting flavor: $FLAVOR"; fi

qemu-system-x86_64 \
  -m 2048 -smp 2 \
  -boot d -cdrom "$ISO" \
  -display none -accel "$ACCEL_USE" \
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
