#!/bin/sh
# Obsidian OS — EXTERNAL KILL SWITCH
# Invoked by:  obsidian-button (hotkey) / killswitch.service (Ghost profile)
# Effect:      1) tear down non-anonymous interfaces
#              2) load kill-switch nft table (Tor-only egress)
#              3) close Cells (sandbox) and unmount removable media
#              4) flush journald + drop caches (Ghost tier)
# Idempotent:  safe to run repeatedly; exits 0.
set -eu

echo "[obsidian] kill switch engaged at $(date -Is)"

# 1) interfaces: bring down everything except lo
for if in $(ip -o link show | awk -F': ' '{print $2}' | grep -v '^lo$'); do
    ip link set "$if" down 2>/dev/null || true
done

# 2) kill-switch firewall (Tor-only egress) if Tor mode enabled
if [ -f /etc/obsidian/ghost/tor-mode ]; then
    nft -f /etc/obsidian/ghost/killswitch.nft
fi

# 3) close all bubblewrap cells
cellmgr --close-all 2>/dev/null || true

# 4) removable media: sync + eject
sync
for dev in /dev/sd?; do
    [ -e "$dev" ] || continue
    if blkid "$dev" >/dev/null 2>&1; then
        udisksctl unmount -b "$dev" 2>/dev/null || true
        udisksctl power-off -b "$dev" 2>/dev/null || true
    fi
done

# 5) Ghost tier: volatile logs already in tmpfs; best-effort cache drop
if [ -f /etc/obsidian/ghost/amnesic ]; then
    echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    journalctl --rotate --vacuum-time=1s 2>/dev/null || true
fi

echo "[obsidian] kill switch complete"
exit 0