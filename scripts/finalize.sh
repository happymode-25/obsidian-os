#!/bin/sh
# debos finalize: hostname, users, firstboot marker, fstab/zram, kernel cmdline
# Called with: finalize.sh <hostname-prefix>
set -eu
HF="${1:-obsidian}"
mkdir -p /etc/obsidian

# hostname + hosts
hostnamectl set-hostname "$HF-$(od -An -N2 -tx /dev/urandom | tr -d ' ' | head -c4)"
printf '127.0.0.1 localhost\n::1 localhost\n' > /etc/hosts

# admin user (password set by firstboot wizard / preseed)
useradd -m -G sudo,libvirt,storage,realtime -s /bin/bash obsidian || true

# swap: zram (encrypted) on all profiles
printf 'zram\n' | tee /etc/modules-load.d/zram.conf >/dev/null
printf 'ALGO=zstd\nPERCENT=50\n' > /etc/default/zramswap

# fstab guard: /home and /var/lib/libvirt separate LUKS2 containers
cat >> /etc/fstab <<'EOF'
# (installer creates these during guided partition)
# UUID=<home>  /home  ext4  defaults,noatime 0 2
# UUID=<varlib> /var/lib/libvirt  ext4  defaults,noatime 0 2
EOF

# network: DNS over TLS via resolved
mkdir -p /etc/systemd/resolved.conf.d
printf '[Resolve]\nDNSOverTLS=opportunistic\nDNSSEC=allow-downgrade\n' \
  > /etc/systemd/resolved.conf.d/obsidian-dns.conf

# kernel cmdline hardening (per profile, appended by bootloader)
printf 'quiet loglevel=3 oops=panic panic_on_warn=1 spectre_v2=on slub_debug=FZ\n' \
  > /etc/obsidian/kernel-cmdline

# firstboot marker
touch /etc/obsidian/firstboot
exit 0