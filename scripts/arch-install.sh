#!/bin/sh
# Called by debos/arch/obsidian-arch.yaml via the `run` action — executes
# INSIDE the Arch chroot. Installs the Obsidian stack equivalent of the apt
# sets in obsidian.yaml. Skeleton: idempotent, non-fatal on missing repo.
set -eu

# base session/security tools (mirrors the debian recipe's first apt block)
pacman -S --noconfirm --needed \
  systemd systemd-boot cryptsetup tpm2-tools lvm2 efibootmgr \
  apparmor nftables zram-generator sudo networkmanager \
  xwayland foot grim slurp wl-clipboard swayidle

# desktop: Obsidian metapackages come from the seeded obsidian repo.
if grep -q '^\[obsidian\]' /etc/pacman.conf 2>/dev/null; then
  pacman -S --noconfirm --needed \
    obsidian-core obsidian-wm obsidian-panel obsidian-apps \
    || echo "obsidian repo not (yet) mirrored — desktop installed manually." >&2
fi

# Ghost extras (privacy-max profile only — package is a no-op elsewhere)
pacman -S --noconfirm --needed tor torsocks veracrypt macchanger secure-delete 2>/dev/null || true

exit 0