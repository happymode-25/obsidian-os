#!/bin/sh
# Called from the debos recipe with the profile name.
# Applies the toolset/secdposture for the chosen profile WITHOUT touching
# network/legal gates (those happen in finalize.sh + firstboot-wizard).
set -eu
PROFILE="$1"

case "$PROFILE" in
  daily-driver)
    apt-get install -y obsidian-desktop obsidian-apps-extra firefox-esr
    ;;
  developer)
    apt-get install -y obsidian-desktop build-essential git curl \
      podman docker.io docker-compose-v2 code-oss jq python3-pip \
      obsidian-agent-cli gh act
    ;;
  pentester)
    apt-get install -y obsidian-desktop
    # The offensive toolset is NOT auto-installed. Security Center materializes
    # /var/lib/obsidian/tools from manifests/tools.yaml at consent time
    # (see firstboot-wizard): "I have authorization" must be checked.
    echo "pentester profile staged (tools gated at consent)" >/etc/obsidian/profile
    ;;
  server)
    apt-get install -y --no-install-recommends obsidian-server-server \
      nginx caddy postgresql sqlite3 docker.io podman netdata
    ;;
  privacy-max)
    apt-get install -y obsidian-desktop obsidian-ghost
    ;;
  *)
    echo "unknown profile: $PROFILE" >&2
    exit 1
    ;;
esac

# record selected profile for firstboot / securityctl
mkdir -p /etc/obsidian
echo "$PROFILE" >/etc/obsidian/profile
ln -sf "/usr/share/obsidian/posture/$PROFILE.conf" /etc/obsidian/posture.conf
exit 0