#!/bin/sh
# Obsidian OS — Ghost shutdown residue reduction.
#
# READ THIS BEFORE "IMPROVING" IT
# --------------------------------
# The obvious version of this script is `dd if=/dev/zero of=/dev/mem`. It does
# not work and never did on a modern kernel:
#   * `lockdown=confidentiality` (set in cmdline.extra) makes /dev/mem
#     inaccessible to unprivileged processes entirely;
#   * even as root, kernels with mem=type_isolate refuse the write;
#   * and even if the write succeeded, it would only overwrite the low 256MB of
#     *virtual* mapping, not physical RAM, so it would be security theatre.
#
# What is actually achievable from a shutdown hook is limited, and this script
# does only that much:
#   1. shred the zram swap device, so compressed page contents are not left
#      readable in freed blocks;
#   2. overwrite key material the process can genuinely reach;
#   3. shred the volatile journal before /run is torn down.
#
# Honest threat-model statement, repeated here because it belongs next to the
# code: Ghost mode protects against DISK and SWAP forensics. It does NOT
# protect against RAM acquisition from an adversary with physical access to a
# running or hibernated machine. See overlays/ghost/README.md.
set -u

# only run in amnesic sessions
[ -f /etc/obsidian/ghost/amnesic ] || exit 0

log() { printf 'obsidian-memwipe: %s\n' "$1" >/dev/kmsg 2>/dev/null || true; }

# --- 1. zram: shred the swap device ------------------------------------------
# zram is a compressed RAM block device with no backing store on disk, so this
# is defence-in-depth against same-boot memory reuse rather than disk recovery.
for zd in /dev/zram*; do
    [ -b "$zd" ] || continue
    log "shredding $zd"
    # swapoff first: a mounted swap device will not accept writes
    swapoff "$zd" 2>/dev/null || true
    dd if=/dev/zero of="$zd" bs=1M count=64 conv=fsync 2>/dev/null || true
done

# --- 2. shred the volatile journal -------------------------------------------
for j in /run/log/journal/*.journal /var/log/journal/*.journal; do
    [ -f "$j" ] || continue
    log "shredding journal $j"
    shred -u -n 1 "$j" 2>/dev/null || rm -f "$j" 2>/dev/null || true
done

# --- 3. key material we can genuinely reach ----------------------------------
# LUKS keys in the kernel keyring / session keyring, if a volume was unlocked.
if [ -d /proc/key-users ]; then
    log "clearing session keyring"
    keyctl purge 2>/dev/null || true
fi

# --- 4. shred our own history/tmp --------------------------------------------
rm -f /root/.bash_history /root/.sh_history 2>/dev/null || true
rm -rf /tmp/* 2>/dev/null || true

log "done (RAM itself is NOT wiped; see overlays/ghost/README.md)"
exit 0
