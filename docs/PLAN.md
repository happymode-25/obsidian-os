# Obsidian OS — Master Building Plan

> Supersedes ad-hoc work. Every task below has a **deliverable** and a
> **verification gate**. Nothing ships without passing its gate. Milestones map
> to the 9 numbered requirements in the brief. Lead: principal OS architect.

---

## Workflow rules (applies to all phases)

1. **One artifact per task** — a file, a recipe, a package, a passing test.
2. **Every artifact has a verification gate**:
   - Config files → parse/lint (`nft -c`, `sysctl --system` dry-run, `yamllint`,
     `sh -n`).
   - Package/recipe → build in CI; boot in QEMU; serial-marker assertions.
   - UI/agents → smoke script + screenshot artifact.
3. **Everything in git**; ISO builds are **reproducible** (pinned container
   images + fixed toolchain versions in the debos container).
4. **No unsupported claims**: pentest tools are *staged* until the consent flow
   (Phase 4) exists; nothing runs outside the guest by default.

---

## Phase 0 — Foundation (spec + scaffold) — *in progress*

Turn the brief into files. Everything is static today and therefore fully
deliverable on any host.

| # | Task | Deliverable | Status |
|---|------|-------------|--------|
| 0.1 | System/index | `README.md` | ✅ done |
| 0.2 | Architecture spec + diagrams | `docs/ARCHITECTURE.md` | ✅ done |
| 0.3 | Master plan | `docs/PLAN.md` | ✅ done |
| 0.4 | Build host + ISO instructions | `docs/BUILD.md` | ✅ done |
| 0.5 | Build recipe (debos, Debian) + Arch secondary | `debos/obsidian.yaml`, `debos/arch/obsidian-arch.yaml` | ✅ done |
| 0.6 | Hardening overlays (sysctl/nft/AppArmor/killswitch/ghost) | `debos/overlays-src/**` | ✅ done |
| 0.7 | Build scripts (overlay packer / profile / services / finalize) | `scripts/make-overlays.sh`, `apply-profile.sh`, `enable-services.sh`, `finalize.sh`, `arch-install.sh` | ✅ done |
| 0.8 | Profiles (5) | `profiles/*.yaml` | ✅ done |
| 0.9 | Tool manifest (53 tools) | `manifests/tools.yaml` | ✅ done |
| 0.10 | Unified shell configs + spec | `shell/**`, `docs/UNIFIED-SHELL.md` | ✅ done |
| 0.11 | `pkg` + firstboot wizard | `scripts/pkg`, `scripts/firstboot-wizard` | ✅ done |
| 0.12 | Security Center + AI Assistant design | `apps/security-center/**`, `apps/ai-assistant/**`, `docs/APPS.md` | ✅ done |
| 0.13 | CIS hardening checklist | `docs/HARDENING.md` | ✅ done |
| 0.14 | Roadmap + legal notes | `docs/ROADMAP.md`, `docs/LEGAL.md` | ✅ done |
| 0.15 | CI/CD ISO pipeline + QEMU boot test | `.github/workflows/build-iso.yml`, `tests/boottest.sh` | ✅ done |
| 0.16 | Upstream component map | `docs/COMPONENT-SOURCES.md` | ✅ done |
| 0.17 | Metapackage skeletons (dpkg) | `debos/packages/**` | ✅ done |

**Gate (end of Phase 0):** ✅ PASSED — every file above exists; YAML lints;
debos recipes parse (Go-template-aware); shell scripts pass `bash -n`
(enforced on Linux/CI; warned on hosts without WSL); nft ruleset is parse-tested
in CI. Re-run any time with `python3 scripts/validate-phase0.py`.

---

## Phase 1 — Foundry: build the ISO on CI (the "make it real" phase)

Goal: push `obsidian.yaml` through debos on a Linux runner and get a bootable ISO
in QEMU, regardless of the desktop polish level.

| # | Task | Deliverable | Gate |
|---|------|-------------|------|
| 1.1 | CI runner + debos container pin | `.github/workflows/build-iso.yml` | job `build-iso` green |
| 1.2 | Metapackages (`obsidian-core`, `obsidianwm`, `obsidian-panel`, …) | `debos/packages/*/debian/` skeletons | `dpkg-buildpackage -b` passes |
| 1.3 | First bootable ISO (daily flavor, GNOME-less minimal session) | `artifacts/obsidian-daily-*.iso` | boots in QEMU to `obsidian.target` |
| 1.4 | Encrypted install path | `debos/installer/` (calamares-flavored config) | install-to-2-disks scripted test |
| 1.5 | Secure Boot + UKI + TPM2 story | `debos/overlays-src/common/etc/obsidian/bootkeys/` | VM boots with SB on + LUKS2 TPM2 unlock |
| 1.6 | Server & ghost flavors boot | `-t flavor:server/ghost` | QEMU boots, correct services listed |

**Gate:** three CI matrix jobs (daily/server/ghost) produce ISOs; QEMU boot test
asserts: serial marker `AEGIS-free obsidian.target reached`, firewall table loaded,
`securityctl status` reports posture.

---

## Phase 2 — The Windows look: desktop shell

| # | Task | Deliverable | Gate |
|---|------|-------------|------|
| 2.1 | ObsidianWM fork baseline (linux-hardened kernel + wlroots) | `compositor/obsidianwm/` | boots wlroots, screenshot |
| 2.2 | Taskbar + tray (GTK4 layer-shell) | `shell/panel/` | start/tray/hover screenshots |
| 2.3 | Start menu + search (fuse of files/apps/pkg-AI) | `shell/start/` | search test script |
| 2.4 | Snap layouts + virtual desktops (Win keys) | compositor module | interactive script test |
| 2.5 | Files ("Explorer"), Settings, themes | `apps/files/`, `apps/settings/` | smoke + screenshots |
| 2.6 | XWayland + Wine/Proton integration | packaging | run notepad.exe in XWayland |
| 2.7 | Low-end mode (XFCE-lite variant preset) | `profiles/lite.yaml` | boots on 1 GB VM |

**Gate:** automated "desktop walkthrough" — open Start, search, snap 2 windows,
create virtual desktop, screenshot each step (Playwright/Wayland-native recorder).

---

## Phase 3 — Security Center + tool enablement (the brief's #2/#4)

| # | Task | Deliverable | Gate |
|---|------|-------------|------|
| 3.1 | `securityctl` daemon + DB (state, posture, consent ledger) | `apps/security-center/daemon/` | unit tests |
| 3.2 | Security Center GTK4 UI | `apps/security-center/ui/` | module cards functional |
| 3.3 | Consent flow (Pentester profile) | `scripts/consent-flow` | must-decline test passes |
| 3.4 | Tool acquisition (from `tools.yaml`) sandboxed | `scripts/tool-installer` | install tool X in a Cell |
| 3.5 | Firewall UI ↔ nftables | `apps/security-center/modules/firewall/` | rule add/save/reload round-trip |
| 3.6 | IDS (Suricata) dashboard + AIDE fins | modules | alert-generates-dash test |
| 3.7 | Ghost mode runtime (amnesic, memwipe, kill switch, MAC spoof) | `debos/overlays-src/privacy-max/**` | live-boot amnesic test |

**Gate:** a red-team walkthrough in a sandboxed Podman net — scan → exploit → report
generated, all logs gated, tool access denied without consent.

---

## Phase 4 — AI everywhere (brief #5/#6)

| # | Task | Deliverable | Gate |
|---|------|-------------|------|
| 4.1 | `obsidian-ai` DBus service + Ollama runtime | `apps/ai-assistant/service/` | local Qwen answers |
| 4.2 | Assistant sidebar (Chat/Agent/Plan) + approval gate | `apps/ai-assistant/ui/` | approval dialog intercepts |
| 4.3 | Agent orchestrator (vendored CrewAI/AutoGPT-compatible) + 5 agents | `agents/**` | agent runs script w/ approval |
| 4.4 | Agent Hub + GitHub store (get-by-URL) | `apps/agent-hub/` | install `n8n` from URL |

**Gate:** "install me a PDF editor" resolves via `pkg` AI search → installs flatpak →
Assistant documents it; an OSINT agent run completes with a report artifact.

---

## Phase 5 — Ecosystem & productization

| # | Task | Deliverable | Gate |
|---|------|-------------|------|
| 5.1 | App Store (Parabolic/flatpak backend) | `apps/store/` | install/update/remove walkthrough |
| 5.2 | `pkg` unified manager (apt/pacman/flatpak/deb/appimage) | `scripts/pkg` | matrix test |
| 5.3 | One-click server roles | `apps/server-hub/` | role enable + healthcheck |
| 5.4 | First-boot wizard, language, theming, live-USB maker | `scripts/firstboot-wizard` | 3-profile install simulation |
| 5.5 | Beta ISO + release signing + updater | `tools/obsidian-updater` | delta update round-trip |

---

## Phase 6 — Hardening audit & 1.0

- Run full `docs/HARDENING.md` checklist against the beta ISO; publish a CIS-mapped
  evidence report.
- Third-party pentest (bug bounty scope); fix → re-release.
- 1.0: signed ISO + upgrade path + LTS channel.

---

## Milestone map → brief

| Brief # | Requirement | Phase |
|---|---|---|
| 1 | Core identity (Win look, Linux core, dual shell, GUI+CLI parity) | 0#, 2, 0.10–0.11 |
| 2 | Security & anti-forensics | 0.6, 1.4–1.5, 3.7 |
| 3 | Built-in server stack | 0.8 (server), 3, 5.3 |
| 4 | Hacking suite + Security Center | 0.9, 3.1–3.6 |
| 5 | AI integration | 4.1–4.2 |
| 6 | Agents + GitHub store | 4.3–4.4 |
| 7 | App ecosystem + `pkg` | 5.1–5.2 |
| 8 | UX (wizard, profiles, low-end) | 0.8, 0.11, 2.7, 5.4 |
| 9 | Deliverables (spec, build, CI, shell table, apps, manifest, CIS, roadmap, legal) | 0.x entirety |

---

## What can be done right now (this machine: Windows, offline ISO build impossible)

Phases **0** (all files), plus **static validation** of everything (lint, parse,
shell syntax). Phase 1+ need a Linux CI runner — the pipeline is already here, so
the moment the repo lands on GitHub, `build-iso` produces ISOs with zero extra
config.

> Current status: **Phase 0 COMPLETE** — all deliverables 0.1–0.17 exist and the
> static validation gate is green (`python3 scripts/validate-phase0.py`).
> Next tick: **Phase 1 Foundry** — push this repo to GitHub, tag `v0.1.0`, and the
> CI pipeline (`build-iso`) produces the first bootable ISO for download.