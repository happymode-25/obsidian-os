#!/usr/bin/env python3
"""Obsidian OS — metapackage scaffold generator.

Emits the debian/ tree for every obsidian-* metapackage that the debos
recipes and profile scripts depend on (see `debos/packages/README.md`),
so the CI `build-packages` job can `dpkg-buildpackage` them all.

Run:  python3 scripts/scaffold-packages.py
Existing packages are not overwritten — missing files (changelog, rules,
install, payload) are created idempotently.
"""
import os
from email.utils import formatdate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.join(ROOT, "debos", "packages")
VERSION = "0.1.0-1"

# name -> (description, depends-list)
PACKAGES = {
    "obsidian-core": (
        "Obsidian OS core: posture, firstboot hooks, /etc/obsidian defaults",
        ["bash", "systemd", "nftables"],
    ),
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
        ["gtk4", "libadwaita-1-0"],
    ),
    "obsidian-agent-cli": (
        "obsidian-agentd orchestrator + automation/security/osint/sysadmin/coding agents",
        ["obsidian-ai", "python3", "podman"],
    ),
    "obsidian-ghost": (
        "Ghost (privacy-max) payloads: volatile journal, memwipe, Tor nm-dispatch, vault",
        ["tor", "torsocks", "obfs4proxy", "macchanger"],
    ),
    "obsidian-server-server": (
        "Server roles template + serverctl (web/db/containers/nas/vm/proxy/ssh/dns/router)",
        ["caddy", "nginx-light", "postgresql", "podman",
         "samba", "nfs-kernel-server", "libvirt-daemon-system"],
    ),
    "obsidian-tool-bootstrap": (
        "reads manifests/tools.yaml, materializes the tool registry (NO offensive tools)",
        ["obsidian-security-center", "git", "curl"],
    ),
    "obsidian-kernel": (
        "obsidian-kernel placeholder (binary built by CI build-kernel job; Provides linux-image-amd64)",
        ["debian-archive-keyring"],
    ),
}

RULES = """#!/usr/bin/make -f
%:
\tdh $@
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

CHANGELOG = """{name} ({version}) unstable; urgency=medium

  * Phase 1 / Foundry: metapackage scaffold.

 -- Obsidian OS <obsidian@localhost>  {date}
"""

INSTALL = "usr/share/obsidian/meta/*\n"


def write_file(path, content, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    if mode is not None:
        os.chmod(path, mode)


def ensure_package(name, desc, deps):
    """Create anything a package dir is missing. Returns (action, kind)."""
    base = os.path.join(PKG_DIR, name)
    debian = os.path.join(base, "debian")
    payload = os.path.join(base, "usr", "share", "obsidian", "meta", name)
    os.makedirs(debian, exist_ok=True)
    os.makedirs(payload, exist_ok=True)

    made = []
    ctl = os.path.join(debian, "control")
    if not os.path.exists(ctl):
        dep_line = ",\n".join("         " + d for d in deps)
        write_file(ctl, CONTROL.format(name=name, desc=desc, deps=dep_line))
        made.append("control")
    rules = os.path.join(debian, "rules")
    if not os.path.exists(rules):
        write_file(rules, RULES, mode=0o755)
        made.append("rules")
    elif not os.access(rules, os.X_OK):
        os.chmod(rules, 0o755)
    inst = os.path.join(debian, "install")
    if not os.path.exists(inst):
        write_file(inst, INSTALL)
        made.append("install")
    clog = os.path.join(debian, "changelog")
    if not os.path.exists(clog):
        write_file(clog, CHANGELOG.format(
            name=name, version=VERSION,
            date=formatdate(localtime=True)))
        made.append("changelog")
    pay = os.path.join(payload, "README.txt")
    if not os.path.exists(pay):
        write_file(pay, f"{name}: Obsidian OS metapackage payload (build-time placeholder).\n")
        made.append("payload")
    return made


def main():
    new_made, ensured = [], []
    for name, (desc, deps) in sorted(PACKAGES.items()):
        if not os.path.exists(os.path.join(PKG_DIR, name, "debian")):
            new_made.append(name)
        made = ensure_package(name, desc, deps)
        if made:
            ensured.append(f"{name}({','.join(made)})")
    print("new packages: " + (", ".join(new_made) if new_made else "none"))
    print("ensured files: " + (", ".join(ensured) if ensured else "all present"))
    print(f"total packages: {len(PACKAGES)}")


if __name__ == "__main__":
    main()