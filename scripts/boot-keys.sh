#!/bin/bash
# Obsidian OS — Secure Boot key tooling (Phase 1.5 story).
# Uses sbctl (keys + enrollment) + systemd ukify (UKI generation).
#   sudo scripts/boot-keys.sh enroll   -> create keys, enroll (with MS keys)
#   sudo scripts/boot-keys.sh sign     -> sign bootloader + all UKIs
#   sudo scripts/boot-keys.sh verify   -> report enrollment + signature status
#   sudo scripts/boot-keys.sh tpm      -> enroll root LUKS2 for TPM2 auto-unlock
set -euo pipefail

say() { printf '%s\n' "$*"; }
die() { say "boot-keys: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root"
command -v sbctl >/dev/null 2>&1 || die "sbctl is not installed (apt install sbctl)"

EFI_LOADER="${EFI_LOADER:-/usr/lib/systemd/boot/efi/systemd-bootx64.efi}"
UKI_DIR="${UKI_DIR:-/boot/EFI/Linux}"
ROOTFS="${ROOTFS:-/}"

cmd_enroll() {
    if sbctl status | grep -q "Setup Mode"; then
        sbctl create-keys
        sbctl enroll-keys --microsoft
        say "Keys created + enrolled (Microsoft keys included for dual-boot)."
    else
        say "Secure Boot is already active — keys exist."
        sbctl status | sed -n '1,12p'
    fi
}

cmd_sign() {
    [ -f "$EFI_LOADER" ] || die "bootloader not found at $EFI_LOADER"
    sbctl sign "$EFI_LOADER"
    for uki in "$UKI_DIR"/*.efi; do
        [ -f "$uki" ] || continue
        sbctl sign "$uki"
        say "signed: $uki"
    done
    say "All boot artifacts signed."
}

cmd_verify() {
    sbctl status
    say "--- signed files ---"
    sbctl verify || true
}

cmd_tpm() {
    # Optional TPM2 auto-unlock: enroll the root LUKS2 container.
    command -v systemd-cryptenroll >/dev/null 2>&1 || die "systemd-cryptenroll missing"
    local dev
    dev="$(findmnt -no SOURCE "$ROOTFS" | head -1)"
    [ -n "$dev" ] || die "cannot resolve root device"
    case "$dev" in /dev/mapper/*) ;; *) die "root is not dm-crypt ($dev) — nothing to unlock" ;; esac
    systemd-cryptenroll --tpm2-device=auto "$dev"
    say "Root container now unlocks with TPM2 at boot."
}

case "${1:-}" in
  enroll) cmd_enroll ;;
  sign)   cmd_sign ;;
  verify) cmd_verify ;;
  tpm)    cmd_tpm ;;
  *) die "usage: boot-keys.sh {enroll|sign|verify|tpm}" ;;
esac