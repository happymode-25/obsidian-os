# Obsidian OS — metapackage skeletons

The debos recipe installs `obsidian-*` packages. Their real `debian/` trees live
under `debos/packages/<pkg>/debian/`. CI builds them (`build-packages` job →
`dpkg-buildpackage -b`) before the ISO build so the recipe always resolves them
from the local repo.

## Package list

| Package | Contents | Depends on |
|---|---|---|
| `obsidian-core` | versions lock, `/etc/obsidian` skeleton, posture defaults | base systemd, cryptsetup, nftables, apparmor, zram-tools |
| `obsidian-kernel` | rebuilt hardened `linux-image` (CI kernel job) | — |
| `obsidianwm` | ObsidianWM compositor + session files | wlroots, xwayland, foot |
| `obsidian-panel` | GTK4 layer-shell Start/taskbar/tray | gtk4-layer-shell, libadwaita |
| `obsidian-apps` | Files, Settings, Store, Firewall UI, Server Hub, VM Manager | gtk4, libadwaita, pcmanfm-backends, libvirt … |
| `obsidian-security-center` | `securityd` daemon + GTK4 Security Center + `securityctl` | `obsidian-apps`, rust toolchain (build-only) |
| `obsidian-ai` | `obsidian-ai` DBus service + sidebar + `obsidianai` CLI | ollama, gtk4 |
| `obsidian-agent-cli` | `obsidian-agentd` + 5 agents (`automation`, `security`, `osint`, `sysadmin`, `coding`) | python3, langchain-core, crewai (vendored) |
| `obsidian-agents-hub` | Agent Hub GUI (`agentctl`) + GitHub-store installer | podman, git, nix |
| `obsidian-desktop` | base desktop incl. lite variant | `obsidian-wm` `obsidian-panel` `obsidian-apps` |
| `obsidian-server-server` | server roles template + `serverctl` | caddy/nginx, postgresql, podman, samba/nfs, libvirt, netdata |
| `obsidian-ghost` | Ghost payloads (volatile journal, memwipe hook, Tor nm-dispatch, vault) | tor, macchanger, veracrypt |
| `obsidian-tool-bootstrap` | `manifests/tools.yaml` + acquisition plumbing (NOT the tools) | security-center |
| `obsidian-live-usb` | Ventoy/miniboot live-USB maker (`scripts/usb-maker`) | ventoy |
| `obsidian-installer` | Calamares guided installer (LUKS2, systemd-boot, SB) | calamares, cryptsetup, sbctl |

## Skeleton example — `obsidian-core`

`debos/packages/obsidian-core/debian/control`:

```
Source: obsidian-core
Section: metapackages
Priority: optional
Maintainer: Obsidian OS <obsidian@localhost>
Standards-Version: 4.7.0
Build-Depends: debhelper-compat (= 13)

Package: obsidian-core
Architecture: all
Depends: systemd,
         systemd-boot,
         cryptsetup,
         nftables,
         apparmor,
         zram-tools,
         sudo,
         bash-completion,
         ${misc:Depends}
Description: Obsidian OS core metapackage
 Locks base versions, seeds /etc/obsidian, installs posture defaults.
```

`debos/packages/obsidian-core/debian/rules`:

```
#!/usr/bin/make -f
%:
	dh $@
```

`debos/packages/obsidian-core/debian/install`:

```
etc/obsidian/*     /etc/obsidian/
usr/share/obsidian/posture/*   /usr/share/obsidian/posture/
```

## Local build one-liner

```bash
(cd debos/packages/obsidian-core && debuild -us -uc -b)   # → ../*.deb
```

CI wraps this loop with `for p in debos/packages/*/; do …; done` and indexes the
resulting `.deb`s into a local apt repo (`dpkg-scanpackages`) so the debos
recipe's `obsidian-*` references resolve reproducibly.