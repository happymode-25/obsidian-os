#!/bin/sh
# debos: enable the right services / boot mode for the flavor being built.
set -eu
FLAVOR="$1"

# common
systemctl enable systemd-networkd systemd-resolved systemd-timesyncd
systemctl enable obsidian-firewall obsidian-aide.timer

case "$FLAVOR" in
  ghost)
    systemctl enable obsidian-tor killswitch.service
    systemctl enable live-boot-obsidian 2>/dev/null || true
    ;;
  penta)
    systemctl enable obsidian-tor 2>/dev/null || true
    systemctl enable securityctl.socket obsidian-ids
    ;;
  server)
    systemctl enable ssh nginx postgresql vmctl.socket nasd
    systemctl disable obsidianwm 2>/dev/null || true
    ;;
  *)
    systemctl enable obsidianwm obsidian-panel obsidian-ai
    ;;
esac

# policy for firstboot
if [ "$FLAVOR" = "ghost" ]; then
    touch /etc/obsidian/ghost/amnesic /etc/obsidian/ghost/tor-mode
fi
exit 0