# Obsidian OS — a Windows-feel Linux, hardened by default

> **Codename:** Obsidian OS (rename = change one string in `debos/obsidian.yaml`).
> **One-liner:** A custom Linux distribution whose desktop is a Windows 11 clone
> (taskbar, Start, tray, Explorer, snap layouts, virtual desktops), whose shell is
> a unified Bash/PowerShell hybrid, and whose default posture is hardened +
> anti-forensic + AI-assisted, with a full pentest suite behind a consent wall.

This repository is the **complete architecture + build scaffold** for the project.
It is not a README-only document set: it contains a working `debos` build recipe,
GitHub Actions ISO pipeline, `tools.yaml` integration manifest, profile manifests,
unified-shell configs, app design specs, and skeleton code for the package manager,
first-boot wizard, Security Center, and AI Assistant.

---

## What you are looking at

| Path | What it is |
|------|-----------|
| `docs/ARCHITECTURE.md` | Full architecture spec (kernel, base, init, DE, security layers, diagrams) |
| `docs/COMPONENT-SOURCES.md` | The upstream open-source map — every project we build on, by layer |
| `docs/BUILD.md` | Build host setup + step-by-step ISO builds (debos/live-build) |
| `docs/UNIFIED-SHELL.md` | The Windows/macOS/Linux unified shell spec + translation tables |
| `docs/APPS.md` | Security Center + AI Assistant app design (UI mockups, tech stack) |
| `docs/HARDENING.md` | Hardening checklist mapped to CIS Debian 12 Benchmark |
| `docs/ROADMAP.md` | MVP → Beta → 1.0 milestone plan |
| `docs/LEGAL.md` | Ethical/legal guardrails (tools disabled by default, consent gating) |
| `debos/obsidian.yaml` | **Working debos recipe** → bootable ISO |
| `debos/overlays/` | Rootfs overlays (sysctl, nftables, kill-switch, firstboot, profiles) |
| `profiles/*.yaml` | Daily Driver / Developer / Pentester / Server / Privacy-Max |
| `manifests/tools.yaml` | Full tool integration manifest (repo URL, install method, GUI status) |
| `shell/` | Unified shell: PowerShell 7 profile + bash aliases + translation shims |
| `apps/security-center/` | Security Center design + daemon skeleton |
| `apps/ai-assistant/` | AI Assistant design + agent skeleton |
| `scripts/pkg` | `pkg` unified package manager (apt/pacman/flatpak/deb/AppImage wrapper) |
| `scripts/firstboot-wizard` | First-boot setup (language / privacy level / profile) |
| `scripts/scaffold-packages.py` | Generates all `obsidian-*` metapackage skeletons for CI |
| `scripts/boot-keys.sh` | Secure Boot key enrollment + UKI signing (sbctl) |
| `scripts/build-kernel.sh` | Builds the hardened `obsidian-kernel` .deb from source |
| `debos/installer/` | Calamares guided installer (LUKS2, systemd-boot, Secure Boot) |
| `.github/workflows/build-iso.yml` | CI/CD that builds and signs ISOs on every tag |

---

## Headline design decisions

1. **Base:** Debian (trixie, rolling channel) primary; Arch secondary recipe attached
   (same config/security overlays, different bootstrap). Kernel: `linux-hardened`.
2. **Init:** systemd default; `runit`/`s6` profile for minimal/server footprints —
   same unit *declarations* compile down to either (see `debos/overlays/s6modes`).
3. **Look (fast path):** KDE Plasma 6 customized into a Windows 11 layout
   (Icons-Only taskbar + Win11 Start + snap layouts + virtual desktops) with a
   Fluent/WhiteSur theme — the fastest route to the Win11 feel on real hardware.
   **Custom path (1.0):** ObsidianWM — a labwc/wlroots compositor fork with
   snap-layout + virtual-desktop logic and a GTK4 layer-shell panel
   (Start / taskbar / tray). Both run the same GTK4/libadwaita Obsidian Apps
   (Files, Settings, App Store, Security Center); XWayland runs Wine/Proton
   windows. Upstream map: `docs/COMPONENT-SOURCES.md`.
4. **Shell:** Bash/zsh/fish as the native engine, PowerShell 7 as the Windows-compat
   layer, and a translation layer so `dir`, `copy`, `Get-Process`, `ls -Force`
   all work in *both* prompts (see `docs/UNIFIED-SHELL.md`).
5. **Security posture** (Per profile):
   - `Standard`: sane defaults, LUKS2 + UKI Secure Boot, AppArmor, firewall.
   - `Hardened`: + lockdown, MAC randomization, DoH, strict sysctl, AIDE, USBGuard.
   - `Ghost` (anti-forensic): amnesic overlay (Tails-style), all-volatile logs,
     memory-wipe-on-shutdown, Tor transparent routing toggle, MAC spoof per boot,
     no telemetry, no swap persistence.
6. **Pentest tools ship but are DISABLED** — only enabled in the Pentester profile
   after an explicit authorization consent step (`firstboot-wizard`). Everything is
   catalogued in `manifests/tools.yaml` behind a single `securityctl enable <tool>`.
7. **AI:** local-first (Ollama) with a provider abstraction (OpenAI/Anthropic/Gemini/
   Groq/vLLM/…). Chat/Agent/Plan modes; terminal execution requires user approval;
   prebuilt agents (automation, security, osint, sysadmin, coding) on a
   CrewAI/AutoGPT-compatible orchestrator (vendored, offline-capable).
8. **Every tool has GUI + CLI parity** — GUI is the GTK4 "Obsidian Apps"; CLI is the
   unified shell. The Security Center, Firewall UI, and AI Assistant all have a
   `xxxctl` CLI equivalent.

---

## Build it yourself

```bash
# host prerequisites (Debian 12/Ubuntu 24.04 or WSL2)
sudo apt install debos whois qemu-utils
git clone https://github.com/YOUR-ORG/obsidian-os
cd obsidian-os
debos -t flavor:daily debos/obsidian.yaml        # → output/obsidian-daily.iso
# or with a profile baked in:
debos -t flavor:penta debos/obsidian.yaml        # Pentester profile
```

Full instructions, kernel patching, secure-boot key setup, and alternative
live-build path: **`docs/BUILD.md`**. CI builds every tag via GitHub Actions →
artifacts in the release (see `.github/workflows/build-iso.yml`).

---

## Status

**Phase 0 (Foundation/scaffold) is complete.** Everything the brief asked for is
in the repo — architecture spec, working build recipes (Debian + Arch), CI/CD
ISO pipeline, unified-shell translation spec, Security Center + AI Assistant
designs, the 53-tool integration manifest, the CIS-mapped hardening checklist,
profiles, roadmap and legal guardrails — and the static validation gate is green
(`python3 scripts/validate-phase0.py`).

Next milestone is *Foundry* (Phase 1): push this repo to GitHub, tag a version,
and the CI pipeline builds the first bootable ISO and boot-tests it in QEMU.
See `docs/ROADMAP.md`.

> **Legal:** This project ships offensive/dual-use tooling *disabled* and gated by
> an authorization-consent flow. Read `docs/LEGAL.md` before enabling the Pentester
> profile. Use only against systems you own or are authorized to test.