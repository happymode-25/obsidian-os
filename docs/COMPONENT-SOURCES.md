# Obsidian OS — Upstream Component Sources (the build-on map)

> Curated from the project's open-source survey. Each entry: **upstream** →
> **how Obsidian uses it** → **where it is referenced** in this repo.
> License notes on every entry; nothing binary-only except optional
> (Binary Ninja, Burp).

Legend — Status: ✅ chosen · ◐ fallback/evaluating · 🔶 optional/plus · ⛔ not used
Layer tags match the architecture layers in `docs/ARCHITECTURE.md`.

---

## 1. OS base & build system

| Upstream | Status | How Obsidian uses it | Where |
|---|---|---|---|
| **Debian trixie** | ✅ working | Sole base image. Bootstrapped by `mmdebstrap` (preferred) or `debootstrap` | `build/build-iso.sh` |
| **Arch Linux** | ⛔ dropped | Was specified as a secondary base. There is no such hybrid base image, and the Arch recipe was unbuildable for the same reasons the Debian one was. See `docs/ADR-0001-debos-replacement.md` | — (removed) |
| **debos / live-build** | ⛔ dropped | Was the build tool. Its `debian-live` action no longer exists upstream and the recipe could never run. Replaced by a plain shell pipeline. Same ADR. | — (removed) |
| **NixOS / nixpkgs** | 🔶 planned | `nix` as the *package builder* for the GitHub store pipeline (reproducible builds inside Cells). Not started. | `docs/UNIFIED-SHELL.md` §3, `scripts/pkg` |
| Fedora kickstarts / Yocto / Void / Alpine | ⛔ | Not used (Debian sole base; Yocto reserved for embedded line-out) | — |
| **Immutable base pattern (ostree, Fedora Silverblue/blendOS idea)** | 🔶 | Roadmap: `ostree`-based immutable "Obsidian Core" image + per-user overlay (daily-driver channel) | `docs/ROADMAP.md` (long tail), deferred |

## 2. Kernel & boot

| Upstream | Status | How | Where |
|---|---|---|---|
| **Linux + linux-hardened** | ⚠️ not built | The hardened config is *specified* but no build step compiles it; the ISO ships the stock trixie `linux-image-amd64`. `scripts/build-kernel.sh` exists but nothing invokes it. | `overlays/common/etc/obsidian/kernel/hardened.config`, `docs/HARDENING.md` |
| **systemd** | ✅ working | Sole init. `systemd-sysv` in every flavor; `systemd-networkd` + `systemd-resolved` provide the net stack. No runit/s6/OpenRC variants — that was part of the dropped multi-base design. | `build/flavors/common.pkgs`, `docs/ARCHITECTURE.md` §4 |
| systemd-boot / shim / MOK / UKI | ⚠️ not wired | Specified, not implemented. `scripts/boot-keys.sh` exists but the image boots BIOS+UEFI GRUB, not a signed UKI. | `docs/ARCHITECTURE.md` §2, `scripts/boot-keys.sh` |
| GRUB2 | ✅ working | Actual loader, BIOS + UEFI, via `grub-mkrescue` | `build/build-iso.sh` §6 |
| Limine / rEFInd | ⛔ | not needed (systemd-boot covers) | — |

## 3. Desktop environment (Windows look)

**Pragmatic route (fast path): prove the look with a proven DE, then customize.**
Obsidian's MVP *desktop* is **KDE Plasma 6** customized into a Windows 11 layout;
the long-term *custom* route keeps **ObsidianWM** (labwc fork + GTK4 layer-shell)
as an independent target. Both share the theme layer and the Obsidian Apps.

| Upstream | Status | How | Where |
|---|---|---|---|
| **KDE Plasma 6 / KWin** | ✅ (fast path) | Win11 layout preset: bottom panel = Icons-Only Task Manager + Start (Kickoff customized) + system tray; snap layouts via KWin Edge-Tiling + `kwin-scripts/snap-helpers`; virtual desktops native | `apps/settings` theme presets; `docs/APPS.md` theme rule |
| **labwc (+ wlroots)** | ◐ (custom route) | fork → ObsidianWM (snap grid, virtual desktops, layer-shell panel) | `docs/ARCHITECTURE.md` §5 |
| GNOME + **Dash to Panel + ArcMenu** | ◐ | alternate GNOME preset (Win-style taskbar + Start) | theme presets |
| **UKUI** (Windows-like DE) | 🔶 | borrow layout/behaviors; not wholesale fork | design reference |
| **Deepin DDE** | 🔶 | borrow window style/animations | design reference |
| **Cinnamon** | 🔶 | fallback for low-end mode (lighter than Plasma) | `profiles/lite` |
| **Xfce** | ✅ (lite) | `lite`/32-bit profile | `profiles/`, low-end mode |
| **Themes:** Fluent-gtk-theme, WhiteSur, Kora, Papirus | ✅ | bundled `obsidian-theme` presets (Fluent = default), Qt6 + GTK + icon set | `docs/APPS.md` §theme |
| Fonts: e.g. Segoe-UI-metrical open font | 🔶 | win 11-feel type scale | theme |

## 4. Core desktop apps (Windows equivalents)

| Windows app | Upstream | Status |
|---|---|---|
| Explorer | Nautilus fork (patched) or Dolphin | ✅ base |
| Settings | GNOME Settings / KDE System Settings as `settingsctl` targets | ✅ |
| Terminal | **BlackBox** (GTK4, Warp-ish) primary; Alacritty/Kitty/WezTerm alternates | ✅ |
| Start/launcher search | **Ulauncher** + **Rofi** (fuzzy) + `pkg` AI search | ✅ |
| Editor/IDE | **VSCodium** + built-in LSP/agent embed | ✅ |
| Browser | **Ungoogled-Chromium** (default) + Firefox-ESR (opt-in) | ✅ |
| Media | VLC + Celluloid + Audacious | ✅ |
| Notepad | GNOME Text Editor (via `notepad` shim) | ✅ |

## 5. Unified shell / PowerShell

| Upstream | Status | How | Where |
|---|---|---|---|
| **PowerShell 7** | ✅ | default interactive shell (Windows habits) | `shell/Microsoft.PowerShell_profile.ps1` |
| bash / zsh / fish | ✅ | Linux natives, Windows-isms loaded via aliases | `shell/bashrc.d/obsidian-aliases.sh` |
| **Nushell** | 🔶 | optional structured layer (`pwrsh -u` flavors) | roadmap |
| **Oh My Posh** | 🔶 | cross-shell prompt themes (star/path/git) | `shell/prompt` |
| **ShellGPT / aichat** | ✅ | terminal AI assist (`obsidianai` backed) | `apps/ai-assistant` |
| busybox-w32 / winbash | ⛔ | unnecessary (shims are native) | — |

## 6. Packaging & App Store

| Upstream | Status | How |
|---|---|---|
| **Flatpak + Flathub** | ✅ | default sandbox store backend |
| **Snap**, **AppImage** + AppImageUpdate | ✅ | alternate backends |
| **Bazaar / GNOME Software / Discover** | ◐ | store UI bases (we ship our own GTK4 store, reuse their role engine) |
| **Wine / Proton + Bottles** | ✅ | Windows app/game layer (XWayland) |
| **Nix** | 🔶 | GitHub-store build sandbox (reproducible) + `chezmoi` config mgmt |
| **Ventoy** | ✅ | live-USB maker backend (`scripts/usb-maker`) |

## 7. Security & hardening core

| Upstream | Status | How |
|---|---|---|
| **kicksecure** | ✅ | hardened Debian base ideas: pre-seeded sysctl, anon profiles, VM-hardening scripts — we cherry-pick its proven configs |
| **LUKS2 / cryptsetup** | ✅ | disk encryption |
| **bubblewrap / Firejail** | ✅ | Cells sandbox | 
| **AppArmor / SELinux** | ✅ / 🔶 | AppArmor default; SELinux optional |
| **nftables + firewalld** | ✅ | firewall engine + optional richer UX |
| **USBGuard**, **ClamAV** | ✅ / ◐ | USB device policy; malware scan (optional) |
| **AIDE**, **osquery** | ✅ / 🔶 | integrity/FIM; telemetry when opted-in |
| **Tails** | ✅ | amnesic live patterns (overlay root, volatile logs, MAC/hostname rotation) |
| **Qubes OS components** | ✅ | Cell isolation semantics inspiration (see `profiles/pentester.yaml` lab_cells) |
| **Whonix + Kicksecure scripts** | ✅ | Tor gateway patterns, hostname rotation, bind-to-Tor |
| **macchanger / iwd** | ✅ | MAC randomization |
| **Tor (torproject)** | ✅ | transparent Tor + kill switch |
| **GrapheneOS concepts** | 🔶 | future mobile line (post-1.0) |

## 8. Firewall / router / server stack

| Upstream | Status | How |
|---|---|---|
| libvirt / QEMU-KVM | ✅ | VM manager + Cells `--vm` |
| **Docker / Podman** | ✅ | container roles |
| **Cockpit** | ✅ | headless server web UI (Server profile) |
| OpenMediaVault / TrueNAS CORE | 🔶 | NAS UI design reference (we build `nasctl` on Samba/NFS + Snapper) |
| **Caddy**, Nginx, PostgreSQL, MariaDB, SQLite | ✅ | server roles |
| **Samba** | ✅ | Windows shares |
| OpenWrt/PF sense ideas (nftables-gw) | ◐ | router/gateway role |

## 9. Security suite (offensive tooling → `manifests/tools.yaml`)

| Upstream | Status | How |
|---|---|---|
| **Kali meta packages / Parrot** | ◐ | source of package sets; NOT wholesale base |
| Metasploit, searchsploit, Nmap, Wireshark, Nuclei, ProjectDiscovery suite, ZAP, Burp CE, Nikto, Aircrack-ng, Kismet, hashcat, John, Ghidra, Cutter, radare2, Volatility 3, Autopsy, Impacket, Responder, BloodHound, Mythic, Havoc, Sliver, AdaptixC2, SpiderFoot, theHarvester, Amass, Maltego CE, PwnDoc-ng, Cervantes, PentestGPT, CAI, HackBot, … | ✅ catalogued | `manifests/tools.yaml` (all gated by consent; C2-labs network-isolated) |
| **CAI (Cybersecurity AI), PentestGPT** | ✅ | added to ai-pentest category |

## 10. AI & agents

| Upstream | Status | How |
|---|---|---|
| **Ollama**, **llama.cpp** | ✅ | local runtime |
| Llama 3.x / Mistral / Qwen / DeepSeek (HF) | ✅ | default model zoo |
| **CrewAI**, **AutoGen**, **LangChain/LlamaIndex** | ✅ | agent orchestrators (vendored, offline-capable) |
| **n8n / Flowise / Dify** | ✅ | Agent Hub automations |
| **Aider / Open Interpreter / Goose / gptme** | ✅ | terminal-agent patterns for `obsidian-agentd` |
| **Jan / Msty** | ◐ | UI design reference only (we ship our own GTK4 sidebar) |

## 11. Automation / dev / utility

**lazygit, fzf, ripgrep, fd, bat, eza, btop** (bundled CLI toolbox) ·
**Ansible** (guest provisioning/seed) · **chezmoi** (dotfiles) ·
**Timeshift / Snapper (btrfs)** (System Restore) · os-prober (dual boot) ·
Ventoy (live USB) — all ✅ bundled; **`restorectl`** wraps snapshots as
"System Restore" points in settings.

## 12. Mobile/IoT (later)

**postmarketOS** (phone Linux), **LineageOS + GrapheneOS hardening** (Android
line), **Zephyr/FreeRTOS** (embedded) — all 🔶 post-1.0 in `docs/ROADMAP.md`.

---

## License & maintenance policy
- All entries are OSI-compatible upstream projects (SPDX noted in the store).
- Obsidian's own code: GPL-3.0 (see `LICENSE`).
- **Component versions are NOT currently pinned.** A previous revision of this
  document claimed they were, in a `debos/components.lock` file that never
  described anything real and has been deleted. The build tracks trixie, so two
  builds of the same commit a month apart legitimately differ.
- **Reproducibility is a Phase 2 goal**, not a present property. The intended
  mechanism is `snapshot.debian.org` (not a lock file: a lock file pins *names*,
  not content, and cannot make a build reproducible). `docs/ROADMAP.md` tracks it.
- Licence exceptions are not limited to OSI-approved. Maltego CE, Binary Ninja
  and Burp Suite CE are free-to-*use* but not redistributable, and are marked
  `status: commercial` in `manifests/tools.yaml`. Several pentest tools are
  dual-use with no OSI licence at all — see `docs/LEGAL.md`.