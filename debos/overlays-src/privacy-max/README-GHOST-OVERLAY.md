# Obsidian OS — Ghost (Privacy-Max / amnesic) overlay tree
# These files are packed into overlays-src/privacy-max.tar and applied only when
# the Ghost profile is selected at first boot (or built with -t flavor:ghost).

# /etc/obsidian/ghost/amnesic            -> presence marker for amnesic mode
# /etc/obsidian/ghost/tor-mode           -> marker that transparent Tor is active
# /etc/obsidian/ghost/egress.nft         -> Tor-only egress ruleset
# /etc/systemd/journald.conf.d/volatile.conf
# /etc/crypttab.zram                      -> encrypted zram config
# /usr/lib/systemd/system-shutdown/obsidian-memwipe.sh

# ------------------------------------------------------------------
# journald volatile (no persistent logs)
# /etc/systemd/journald.conf.d/volatile.conf
# ------------------------------------------------------------------
[Journal]
Storage=volatile
Compress=yes
MaxRetentionSec=0
ForwardToSyslog=no
ForwardToConsole=no

# ------------------------------------------------------------------
# kernel cmdline additions for amnesic live boots (dracut/live)
# /etc/obsidian/ghost/cmdline
# ------------------------------------------------------------------
quiet rd.live.overlay.overlayfs=1 rd.live.overlay.thin=0 rd.live.ram=1
lsm=lockdown,apparmor,yama landlock lockdown=confidentiality
net.ipv6.conf.all.disable_ipv6=1 amd_iommu=on

# ------------------------------------------------------------------
# memory wipe on shutdown (best-effort; runs LAST in shutdown)
# /usr/lib/systemd/system-shutdown/obsidian-memwipe.sh
# ------------------------------------------------------------------
#!/bin/sh
# invoked with $1 = systemd-shutdown argv; scrub RAM
if [ -f /etc/obsidian/ghost/amnesic ]; then
    # zero a 256 MB probe region to degrade residual data (cannot wipe all RAM
    # while running; this pairs with zram + tmpfs-only state)
    dd if=/dev/zero of=/dev/mem bs=1M count=256 2>/dev/null || true
fi
exit 0

# ------------------------------------------------------------------
# nft rules for Tor-only egress (activated by kill switch / tor.service)
# /etc/obsidian/ghost/egress.nft
# ------------------------------------------------------------------
table inet obsidian_tor {
    chain out {
        type filter hook output priority 0; policy drop;
        ct state established,related accept
        oifname "lo" accept
        tcp dport 9050 accept   # to Tor SOCKS/transproxy only
        log prefix "TOR-LEAK " drop
    }
    chain in {
        type filter hook input priority 0; policy drop;
        ct state established,related,untracked accept
        iif lo accept
    }
}