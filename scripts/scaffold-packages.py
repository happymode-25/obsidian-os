#!/usr/bin/env python3
"""Obsidian OS — metapackage scaffold generator.

Emits the debian/ tree for every obsidian-* metapackage that the debos
recipes and profile scripts depend on (see `debos/packages/README.md`),
so the CI `build-packages` job can `dpkg-buildpackage` them all.

Run:  python3 scripts/scaffold-packages.py          # pylint: disable=all
Existing packages are left untouched (obsidian-core already has a bespoke
payload): only missing ones are created.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.join(ROOT, "debos", "packages")

# name -> (description, depends-list)
PACKAGES = {
    "obsidianwm": (
        "ObsidianWM compositor (wlroots fork) + session files",
        ["wlroots", "xwayland", "foot", "libinput10", "swaybg", "bemenu"],
    ),
    "obsidian-panel": (
        "GTK4 layer-shell shell: Start / taskbar / tray / quick settings",
        ["gtk4", "libadwaita-1-0", "gtk4-layer-shell"],
    ),
    "obsidian-apps": (
        "Obsidian Apps: Files, Settings, Store, Firewall UI, Server Hub, VM Manager",
        ["gtk4", "libadwaita-1-0", "flatpak", "libvirt-daemon-system"],
    ),
    "obsidian-apps-extra": (
        "Extra bundled desktop apps: office, media, store favourites",
        ["libreoffice", "gimp", "vlc", "obsidian-store"],
    ),
    "obsidian-desktop": (
        "Obsidian desktop session (wm + panel + apps + lite fallback)",
        ["obsidianwm", "obsidian-panel", "obsidian-apps", "pipewire", "wireplumber"],
    ),
    "obsidian-security-center": (
        "securityd daemon + GTK4 Security Center + securityctl CLI",
        ["obsidian-apps", "nftables", "aide", "suricata", "libnftables1"],
    ),
    "obsidian-ai": (
        "obsidian-ai DBus service, assistant sidebar, obsidianai CLI",
        ["ollama", "gtk4", "libadwaita-1-0"],
    ),
    "obsidian-agent-cli": (
        "obsidian-agentd orchestrator + automation/security/osint/sysadmin/coding agents",
        ["obsidian-ai", "python3", "podman"],
    ),
    "obsidian-ghost": (
        "Ghost (privacy-max) payloads: volatile journal, memwipe, Tor nm-dispatch, vault",
        ["tor", "torsocks", "obfs4proxy", "macchanger", "veracrypt", "secure-delete"],
    ),
    "obsidian-server-server": (
        "Server roles template + serverctl (web/db/containers/nas/vm/proxy/ssh/dns/router)",
        ["caddy", "nginx-light", "postgresql", "podman",
         "samba", "nfs-kernel-server", "libvirt-daemon-system", "netdata"],
    ),
    "obsidian-tool-bootstrap": (
        "reads manifests/tools.yaml, materializes the tool registry (NO offensive tools)",
        ["obsidian-security-center", "git", "curl"],
    ),
}

RULES = """#!/usr/bin/make -f
%:
	dh $@
"""

CONTROL = """Source: {name}
Section: metapackages
Priority: optional
Maintainer: Obsidian OS <obsidian@localhost>
Standards-Version: 4.7.0
Build-Depends: debhelper-compat (= 13)

Package: {name}
Architecture: all
Depends: {deps},
         ${{misc:Depends}}
Description: {desc}
"""

INSTALL = "usr/share/obsidian/meta/*\n"


def scaffold(name, desc, deps):
    base = os.path.join(PKG_DIR, name)
    debian = os.path.join(base, "debian")
    payload = os.path.join(base, "usr", "share", "obsidian", "meta", name)
    os.makedirs(debian, exist_ok=False)
    os.makedirs(payload, exist_ok=True)
    dep_line = ",\n".join("         " + d for d in deps)
    with open(os.path.join(debian, "control"), "w", encoding="utf-8") as fh:
        fh.write(CONTROL.format(name=name, desc=desc, deps=dep_line))
    with open(os.path.join(debian, "rules"), "w", encoding="utf-8",
              newline="") as fh:
        fh.write(RULES)
    os.chmod(os.path.join(debian, "rules"), 0o755)
    with open(os.path.join(debian, "install"), "w", encoding="utf-8") as fh:
        fh.write(INSTALL)
    with open(os.path.join(payload, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"{name}: Obsidian OS metapackage payload (build-time placeholder).\n")
    return name


def main():
    made, kept = [], []
    for name, (desc, deps) in sorted(PACKAGES.items()):
        debian = os.path.join(PKG_DIR, name, "debian")
        if os.path.exists(debian):
            kept.append(name)
            continue
        made.append(scaffold(name, desc, deps))
    print("scaffolded: " + ", ".join(made) if made else "none new")
    if kept:
        print("kept existing: " + ", ".join(kept))
    print(f"total packages: {len(made) + len(kept)}")


if __name__ == "__main__":
    main()