#!/bin/bash
# Obsidian OS — headless QEMU boot smoke test.
# Usage: tests/boottest.sh <image.iso> [marker] [timeout_s]
#   Boots the image with serial console to a file; exits 0 when MARKER appears,
#   1 on timeout / crash. Used by CI and docs/BUILD.md §3.
set -euo pipefail

ISO="${1:?usage: boottest.sh <image> [marker] [timeout_s]}"
MARKER="${2:-obsidian.target reached}"
TIMEOUT="${3:-240}"

[ -f "$ISO" ] || { echo "ISO not found: $ISO" >&2; exit 1; }

LOG="$(mktemp /tmp/obsidian-boot-XXXX.log)"
cleanup() { pkill -f "qemu-system.*${ISO##*/}" 2>/dev/null || true; rm -f "$LOG"; }
trap cleanup EXIT

echo "boot-test: $ISO"
echo "marker:    '$MARKER'  (timeout ${TIMEOUT}s)"

# -accel tcg works everywhere; drop to serial-only output.
qemu-system-x86_64 \
  -m 2048 -smp 2 \
  -boot d -cdrom "$ISO" \
  -display none -accel tcg \
  -serial file:"$LOG" &

QPID=$!
for _ in $(seq 1 "$TIMEOUT"); do
  kill -0 "$QPID" 2>/dev/null || break
  if grep -qF "$MARKER" "$LOG"; then
    echo "BOOTTEST PASS: marker '$MARKER' seen after ${_:-?}s"
    exit 0
  fi
  sleep 1
done

echo "BOOTTEST FAIL: marker '$MARKER' not seen in ${TIMEOUT}s" >&2
echo "--- last serial output ---" >&2
[ -f "$LOG" ] && tail -60 "$LOG" >&2 || true
exit 1