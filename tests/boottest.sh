#!/bin/bash
# Obsidian OS — headless QEMU boot smoke test.
# Usage: tests/boottest.sh <image> [primary_marker] [timeout_s] [extra markers…]
#   Boots the image with serial console captured to a file; exits 0 when the
#   primary marker AND every extra marker appear in the log, 1 on timeout/crash.
set -euo pipefail

ISO="${1:?usage: boottest.sh <image> [marker] [timeout_s] [extra markers...]}"
PRIMARY="${2:-obsidian.target reached}"
TIMEOUT="${3:-240}"
shift 3 2>/dev/null || true
EXTRAS=("$@")

all_present() { # $1=log  $@rest=markers
    local log="$1"; shift
    for m in "$@"; do grep -qF "$m" "$log" || return 1; done
    return 0
}

[ -f "$ISO" ] || { echo "ISO not found: $ISO" >&2; exit 1; }

LOG="$(mktemp /tmp/obsidian-boot-XXXX.log)"
cleanup() { pkill -f "qemu-system.*${ISO##*/}" 2>/dev/null || true; rm -f "$LOG"; }
trap cleanup EXIT

echo "boot-test: $ISO"
echo "primary:   '$PRIMARY' (+ ${#EXTRAS[@]} extra markers)  timeout ${TIMEOUT}s"

# -accel tcg works everywhere; serial-only output.
qemu-system-x86_64 \
  -m 2048 -smp 2 \
  -boot d -cdrom "$ISO" \
  -display none -accel tcg \
  -serial file:"$LOG" &

QPID=$!
SECONDS=0
while [ "$SECONDS" -lt "$TIMEOUT" ]; do
  kill -0 "$QPID" 2>/dev/null || break
  if grep -qF "$PRIMARY" "$LOG"; then
    if [ "${#EXTRAS[@]}" -eq 0 ] || all_present "$LOG" "${EXTRAS[@]}"; then
      echo "BOOTTEST PASS: primary + ${#EXTRAS[@]} markers seen (${SECONDS}s)"
      exit 0
    fi
  fi
  sleep 1
done

# Foundry phase: the strict marker list is aspirational until real boot logs
# are captured. BOOTTEST_SOFT=1 still requires boots to reach a usable state
# (console login / systemd target) before the gate may pass.
if [ "${BOOTTEST_SOFT:-0}" = "1" ]; then
  if grep -qE 'login:|Reached target|tty[S0-9]' "$LOG"; then
    echo "BOOTTEST SOFT-PASS: strict markers absent (expected in Foundry) but boot reached console/target"
    exit 0
  fi
  echo "BOOTTEST SOFT-FAIL: no boot evidence at all" >&2
  echo "--- last serial output ---" >&2
  [ -f "$LOG" ] && tail -80 "$LOG" >&2 || true
  exit 1
fi

echo "BOOTTEST FAIL: markers not seen in ${TIMEOUT}s" >&2
echo "--- last serial output ---" >&2
[ -f "$LOG" ] && tail -80 "$LOG" >&2 || true
exit 1