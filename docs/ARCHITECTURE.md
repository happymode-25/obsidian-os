# Obsidian OS — Architecture Specification

Version: 0.1 (Foundry checkpoint) · Authors: Principal OS Architect

---

## 1. System overview

```
                 ┌─────────────────────────────────────────────────────────┐
   HARDWARE      │ UEFI (SB enrolled) · TPM 2.0 · storage · NIC(s) · GPU   │
                 └──────────────┬──────────────────────────────────────────┘
                                │
                 ┌──────────────▼──────────────────────────────────────────┐
   BOOT CHAIN    │ systemd-boot (UKI) → Secure Boot (shim/mok)             │
                 │ → LUKS2 (GRUB dh or UKI-LUKS) → kernel (locked-down)    │
                 └──────────────┬──────────────────────────────────────────┘
                                │
                 ┌──────────────▼──────────────────────────────────────────┐
   KERNEL        │ linux-hardened 6.x · lockdown=integrity/confidentiality │
                 │ LSM=apparmor · netfilter/nftables · io_uring disabled   │
                 │ zram(encrypted) · hardened sysctl (per profile)         │
                 └──────────────┬──────────────────────────────────────────┘
                                │
       ┌────────────────────────┼─────────────────────────────┐
       ▼                        ▼                             ▼
┌──────────────┐       ┌────────────────┐              ┌────────────────┐
│  SYSTEMD     │       │  RUNIT/S6      │              │  GHOST MODE   │
│  (default)   │       │  (minimal      │              │  amnesic ·    │
│              │       │   / server)    │              │  log-less     │
└──────────────┘       └────────────────┘              └────────┬───────┘
                                                               │ opt-in
                 ┌──────────────────────────────────────────────▼────────┐
   SESSION       │ Wayland compositor: ObsidianWM (wlroots fork)          │
                 │  • snap layouts · virtual desktops · focus engine      │
                 │  • XWayland (Wine/Proton/v4 keys)                      │
                 │  GTK4 layer-shell panel: Taskbar · Start · Tray        │
                 │  Obsidian Apps (GTK4/libadwaita): Files, Settings,     │
                 │  App Store, Security Center, AI Assistant, Agent Hub,  │
                 │  Firewall UI, NAS UI, VM Manager                        │
                 └──────────────┬──────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────────┐
        ▼                       ▼                           ▼
┌──────────────┐      ┌────────────────────┐       ┌──────────────────────┐
│ UNIFIED SHELL│      │ APP SANDBOX        │       │ AI + TOOLING         │
│ bash/zsh     │      │ bubblewrap/firejail│       │ Ollama (local)       │
│ pwsh7 shim   │      │ Obsidian Cells     │       │ provider gateway     │
│ pkg manager  │      │ (Qubes-style)      │       │ Security Center      │
└──────────────┘      └────────────────────┘       │ agents · agent hub   │
                                                   └──────────────────────┘
```

## 2. Kernel, boot, and encryption

- **Kernel:** `linux-hardened` (Debian source build with hardened baseline: hardened
  allocator, `CONFIG_RANDOMIZE_KSTACK_OFFSET_DEFAULT`, `CONFIG_STRICT_KERNEL_RWX`,
  `CONFIG_SLAB_FREELIST_RANDOM`, `CONFIG_INIT_ON_ALLOC/FREE`, hardened usercopy,
  `CONFIG_SECURITY_LOCKDOWN_LSM=y`).

  > **Not yet true of the produced ISO.** `overlays/common/etc/obsidian/kernel/hardened.config`
  > records the intended config, and `scripts/build-kernel.sh` exists, but no
  > build step runs it. The ISO currently boots the stock trixie
  > `linux-image-amd64`, so none of the above hardening is actually in the
  > kernel. This is the largest remaining architectural gap — see
  > `docs/GAP-REPORT.md` §7 and `docs/ROADMAP.md`.
- **Boot:** systemd-boot + **UKI** (`systemd-stub`) so LUKS2 passphrase can be
  integrated; Secure Boot via shim/MOK with user keys; TPM2 measured boot
  (`systemd-measure`) + optional auto-unlock via `systemd-cryptenroll --tpm2-device`.
- **Lockdown:** kernel cmdline `lockdown=confidentiality` in Hardened/Ghost profiles
  (disables loadable unsigned modules, hibernation, kexec, perf, BPF unless signed).
- **Filesystems:** root `/`, `/home`, and `/var/lib/libvirt` each in their own LUKS2
  container (Argon2id, XTS-AES-256); `/boot` on its own small ESP; swap = encrypted
  zram (`zswap`+`zram` with `sysctl vm.swappiness=10`); `fstab` uses UUIDs + `nofail`.
- **Verity (hardening tier):** `/usr`/`/etc` overlay via dm-verity for read-only
  system verification (Advanced profile; off for daily-driver to keep updates simple).

### Boot chain diagram

```
UEFI ─▶ shim ─▶ systemd-boot ─▶ UKI (.efi) ─▶ systemd-stub
        │               │
        ▼               ▼
  MOK keys        initrd: decrypt LUKS2 via TPM2 or passphrase
                          │
                          ▼
                 mount root → /usr·/run · /var ... → systemd → obsidian.target
```

## 3. Base distribution & packaging

- **Single base:** Debian trixie with `contrib`, `non-free-firmware`.

  > **A second base was specified and has been dropped.** An earlier revision
  > of this document called for an optional Arch rootfs via an `arch-bootstrap`
  > recipe, giving `pkg` two backends (`apt` / `pacman`) behind one manifest.
  > There is no such hybrid base image, and the Arch recipe was unbuildable for
  > the same reasons the Debian one was. Decision recorded in
  > `docs/ADR-0001-debos-replacement.md`. `pkg` is therefore a single-backend
  > (`apt` + `flatpak`) resolver, and the manifest is not a cross-distro one.
- **Version pinning:** an `obsidian-core` metapackage is intended to pin
  versions. It does not exist yet — the `debos/packages/**` dpkg skeletons are
  hollow (they install a README and nothing else), and the `components.lock`
  they referenced has been removed. See `docs/ROADMAP.md` Phase 2.
- **Rolling vs stable:** install-time choice (wizard). Rolling = trixie+SID channel;
  stable = trixie+security freeze. Both share the hardened kernel and overlays.

## 4. Init system

- **Default:** `systemd` — birth of all core units below.
- **Minimal/server profile:** `s6`/`runit` supervisor with equivalent unit set.
  Units are written once in a neutral DSL (`obsidian-units`), compiled to
  `systemd` or `s6` service files at firstboot — keeps the "Windows or minimal"
  promise without forking service code.

Core services (`systemd/obsidian.target`):
| Unit | Purpose |
|---|---|
| `obsidianshell.service` | ObsidianWM + panel session |
| `securityctl.socket` | Security Center daemon (DBus + AF_UNIX) |
| `obsidian-firewall.service` | nftables ruleset loader + healthcheck |
| `obsidian-ids.service` | Suricata daemon (flows to Security Center) |
| `obsidian-aide.service` | FIM scan (timer) |
| `obsidian-tor.service` | Tor daemon when Ghost/Privacy profile enabled |
| `obsidian-ai.service` | Ollama (local LLM inference) |
| `obsidian-store.service` | App Store index + update service |
| `cellmgr.service` | bubblewrap cell launcher (isolation) |

## 5. Desktop environment — the "Windows look"

Two routes, one theme layer (upstream map in `docs/COMPONENT-SOURCES.md` §3):

- **Fast path (MVP):** **KDE Plasma 6** customized into a Windows 11 layout —
  bottom panel = Icons-Only Task Manager + Win11-style Start (customized
  Kickoff) + system tray; snap layouts via KWin tiling + helper script; virtual
  desktops native; theme = Fluent-gtk-theme/WhiteSur + Kora icons. Proven code,
  fastest to the "feels like Windows" demo on real hardware.
- **Custom path (1.0 target):** `ObsidianWM` — a curated fork of `labwc`
  (wlroots, Wayland) for a fully bespoke Fluent shell. Both paths run the same
  GTK4/libadwaita Obsidian Apps, the same `obsidian-theme` package, and the same
  unified shell.

Compositor details (custom path):
  - **Snap layouts** (Windows 11-style hot zones): on titlebar hover a 6-zone grid
    overlays; choosing a zone materials the window into a computed tiling slot;
    `Win+←/→/↑/↓` do classic Win key snapping; `Win+Z` toggles the grid.
  - **Virtual desktops:** `Win+Ctrl+←/→`; taskbar thumbnails per desktop; per-app
    desktop assignment.
  - **Taskbar behaviors:** running + pinned apps, grouped thumbnails, hover preview,
    system tray (tray icons over layer-shell), clock/calendar popover.
  - **XWayland** for Wine/Proton and legacy apps; fractional scaling per output.
- **Shell panel:** GTK4 + `gtk4-layer-shell` — Start (searchable, pinned, folders,
  "all apps" grid), notification center (modern flyout), quick settings (WiFi/
  airplane/bluetooth/dark mode/Do Not Disturb), tray, virtual desk pills.
- **Start menu "Run + Search"**: merges files, apps, and **`pkg` AI search**
  results ("install me a PDF editor" works here).
- **Themes:** light/dark + accent; Windows 10/11, macOS, GNOME presets (GTK,
  Kvantum/Qt6, and ObsidianWM colors under one `obsidian-theme` package).

### Windows-like app suite (Obsidian Apps, GTK4/libadwaita)
| App | GUI (GTK4) | CLI alias |
|---|---|---|
| Files ("Explorer") | sidebar, tabs, drag-and-drop, network mounts | `obsidian-files` → also `explorer` |
| Settings ("Control Panel") | categorized settings, searchable | `settingsctl` |
| App Store | cards, categories, update all | `pkg search/install` |
| Security Center | dashboard + module cards | `securityctl` |
| Firewall UI | inbound/outbound rules, profiles | `firewallctl` (`nft`) |
| NAS UI | Samba/NFS shares, users, snapshots | `nasctl` |
| VM Manager | libvirt storage/network/adapter | `vmctl` |
| Agent Hub | install/configure agents & automations | `agentctl` |

## 6. Security & anti-forensics

### Layered defenses (bottom-up)
1. **Boot:** Secure Boot + UKI + TPM2 + optional dm-verity.
2. **Storage:** LUKS2 everywhere writable; encrypted zram swap.
3. **Kernel:** lockdown, hardened config, `kptr_restrict`, `dmesg_restrict`,
   `kernel.unprivileged_bpf_disabled`, `net.core.bpf_jit_harden=2`, no
   unprivileged user namespaces where incompatible caps are disabled
   (`kernel.unprivileged_userns_clone=0` when not needed).
4. **MAC:** AppArmor profiles for every obsidian service + browser +
   sandboxed apps; `aa-enforce` by default (Hardened+).
5. **Sandbox:** every installed app runs in a `bubblewrap` **cell** (dedicated
   private `/home`, no network, tmpfs) unless the user grants capabilities —
   `Obsidian Cells` mimics Qubes compartmentalization; optional KVM disposable
   VMs (`cellmgr --vm`).
6. **Network:** `nftables` default-deny inbound; Suricata IDS inline; per-network
   random MAC + hostname; DoH (systemd-resolved `DNSOverTLS/HTTPS`); optional
   transparent Tor (`obsidian-tor` with kill-switch rules that DROP non-Tor
   traffic if the circuit drops).
7. **Integrity:** AIDE-in-DB (daily), kernel module signing, `fapolicyd` allowlist
   in Hardened profile.

### Anti-forensics (Ghost profile / amnesic mode)
| Capability | Mechanism |
|---|---|
| Amnesic mode | Live overlay root (tmpfs over read-only squashfs), nothing persists |
| Log-less | `journald` in volatile mode; `/var/log` → tmpfs; no core dumps (`coredump=0`) |
| Memory wipe | systemd shutdown hook zeroes RAM (best-effort PMEM/RAM scrub loop) |
| MAC spoof | per-boot random MAC via NetworkManager dispatcher script |
| Hostname rot | random `.onion`-style hostname per boot |
| Tor-only egress | kill-switch nftables chain; UDP/TCP leak guard; DNS over Tor |
| VPN chains | WireGuard-first, Tor-second layered `wg+tor` profiles (chain order selectable) |
| Vault | VeraCrypt-compatible container creator + mount in Security Center |
| No persist swaps | zram only; spindown + `blkdev` secure-erase hooks when partition table securely removed |

### The kill switch (hardware/UI)
`Obsidian Button` — global hotkey + a systemd service `killswitch.service` that
tears down non-anonymous interfaces, flushes cookies, closes Cells, and (Ghost)
ejects + zeroes removable media. One keystroke, idempotent, testable.

## 7. Built-in server stack (one-click enable)

`securityctl server enable <role>` writes config, opens firewall ports in an
explicit ruleset, launches services, and emits `serverctl status` (GUI: Server Hub).

| Role | Stack | UI |
|---|---|---|
| Web | Caddy (auto-TLS) or Nginx | Server Hub site panel |
| Database | PostgreSQL 17 (+ SQLite), encrypted datadir | db panel |
| Containers | Docker + Podman (rootless default) | container panel |
| VMs | libvirt/KVM via VM Manager | VM panel (Proxmox-style) |
| NAS | Samba + NFS + snapshots | NAS UI |
| Reverse proxy | Caddy/Nginx conf generator | proxy panel |
| SSH | hardened sshd (key-only, `sshd` config generator) | ssh panel |
| DNS | CoreDNS local resolver (ad-block lists optional) | dns panel |
| Router/gateway | nftables + DHCPd + WAN failover (pfSense-flavor) | gateway panel |

## 8. Security Center (unified hacking suite)

GUI-first launcher built from `manifests/tools.yaml`. Every tool:
`installed | disabled | requires-consent`. Disabled by default; a tool becomes
runnable only after: (1) Pentester (or Server+redteam) profile active, and
(2) per-tool authorization in the consent flow.

Modules: **Grade** (readiness), **Recon/OSINT**, **Scan**, **Web**, **Wireless**,
**Password**, **C2-labs** (closed network only), **Forensics**, **Reporting**,
**Hardware**. See `docs/APPS.md` + `manifests/tools.yaml`.

## 9. AI integration

- **Runtime:** Ollama (local, offline) hosting Llama/Mistral/Qwen; optional
  provider gateway (OpenAI, Anthropic, Gemini, Groq, Mistral, vLLM, LM Studio…)
  behind one `obsidian-ai` DBus API.
- **Assistant shell:** GTK4 sidebar overlay (Ctrl+Space). Modes:
  - **Chat** — RAG over local docs + system state.
  - **Agent** — multi-step; every terminal command goes through an approval
    dialog (polkit-style) unless the user grants a scoped trust.
  - **Plan** — builds an executable plan (markdown + steps) with rollback points.
- **Tools:** the assistant can drive `securityctl`, `pkg`, `vmctl`, `nasctl`,
  report generation, and predict next toolchain for a task.
- **Multi-agent:** vendored Orchestrator (CrewAI/AutoGPT-compatible) with agents:
  `automation`, `security`, `osint`, `sysadmin`, `coding`; Agent Hub one-click
  installs n8n/Flowise/Dify workflows bound to these agents.

## 10. App ecosystem & GitHub store

- **App Store:** Flatpak (sandboxed, recommended), deb, AppImage, Snap, GitHub
  Release containers. Wine + Proton (gaming) via a toggle profile; NVIDIA/AMD
  driver auto-installer (signed where possible).
- **Get-from-GitHub:** paste a repo URL → `agentctl` clones it, selects the build
  pipeline by heuristics (`flatpak manifest` → `deb` → `AppImage` → `justfile`),
  builds in a disposable cell, and installs sandboxed. Auto-update runs daily in
  the user's schedule window.

## 11. Profiles (first-boot wizard)

| Profile | Posture | Toolset | Footprint |
|---|---|---|---|
| Daily Driver | Standard | browser, office, media, Wine | default DE |
| Developer | Standard+ | editors, containers, git, CI agents | default DE |
| Pentester | Hardened+ | **full offensive suite (consent-gated)** | default DE + Cells |
| Server | Hardened | web/db/nas/vm/router stacks | headless (runit/s6 optional) |
| Privacy-Max | Ghost | Tor, amnesic mode toggle, MAC spoof, vault | amnesic overlay |

The wizard also sets language, keyboard, privacy tier, channels (rolling/stable),
and grants/denies the pentest consent step ("I will only use these tools on
systems I own or have written authorization to test").

## 12. Telemetry & privacy

None by default (Ghost: nothing, ever). Optional opt-in "crash only" telemetry in
Daily Driver builds (hostname/counters only, no content, GUI toggle, audit log).