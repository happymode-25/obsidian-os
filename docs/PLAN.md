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
3. **Everything in git**; ISO builds are **reproducible** (fixed `SOURCE_DATE_EPOCH`
   + emptied `machine-id`; package versions are pulled from the mirror, not pinned —
   exact `snapshot.debian.org` pinning is tracked in the roadmap; see `docs/BUILD.md` §7).
4. **No unsupported claims**: pentest tools are *staged* until the consent flow
   (Phase 4) exists; nothing runs outside the guest by default.

---

## Phase 0 — Foundation (spec + scaffold) — *done, but overstated*

Turn the brief into files.

> **Correction (2026-09-27).** This phase was previously marked complete and
> partially was not. The ISO recipe could not build, its `run` actions executed on
> the build host instead of the image, four of six overlay directories did not
> exist, the Ghost overlay was a single README, and the boot test could not
> distinguish the project's image from stock Debian. Full evidence and remediation
> in **[`GAP-REPORT.md`](GAP-REPORT.md)**. The statuses below have been corrected
> to match the code rather than the original claim.

| # | Task | Deliverable | Status |
|---|------|-------------|--------|
| 0.1 | System/index | `README.md` | ✅ done (rewritten to state real status) |
| 0.2 | Architecture spec + diagrams | `docs/ARCHITECTURE.md` | ✅ done |
| 0.3 | Master plan | `docs/PLAN.md` | ✅ done |
| 0.4 | Build host + ISO instructions | `docs/BUILD.md` | ✅ done (rewritten for the new pipeline) |
| 0.5 | Build recipe | ~~`debos/obsidian.yaml`~~ → `build/build-iso.sh` | 🔴 **was unbuildable** — removed, replaced |
| 0.5b | Arch secondary base | ~~`debos/arch/obsidian-arch.yaml`~~ | 🔴 **removed** — same bugs; a second base contradicts the one-base decision |
| 0.6 | Hardening overlays (sysctl/nft/AppArmor/killswitch/ghost) | `overlays/common/**`, `overlays/ghost/**` | 🟡 **3 real rule-order bugs fixed**; Ghost was a README, now real files |
| 0.7 | Build scripts | `build/build-iso.sh` | 🔴 **3 removed** (build-time-only, superseded); `apply-profile.sh` + `finalize.sh` kept — they run *in-image* from the firstboot wizard |
| 0.8 | Profiles (5) | `profiles/*.yaml` | ✅ done |
| 0.9 | Tool manifest | `manifests/tools.yaml` | 🟡 **53 tools listed, ~13 URLs fabricated; tiers 11.6/11.7/11.9–11.11 missing** |
| 0.10 | Unified shell configs + spec | `shell/**`, `docs/UNIFIED-SHELL.md` | ✅ done |
| 0.11 | `pkg` + firstboot wizard | `scripts/pkg`, `scripts/firstboot-wizard` | ✅ done |
| 0.12 | Security Center + AI Assistant design | `apps/**`, `docs/APPS.md` | ✅ design only — not built |
| 0.13 | CIS hardening checklist | `docs/HARDENING.md` | ✅ done |
| 0.14 | Roadmap + legal notes | `docs/ROADMAP.md`, `docs/LEGAL.md` | ✅ done |
| 0.15 | CI/CD ISO pipeline + QEMU boot test | `.github/workflows/build-iso.yml`, `tests/boottest.sh` | 🔴 **rewritten** — old CI uploaded an artifact nothing consumed and ran a tautological gate |
| 0.16 | Upstream component map | `docs/COMPONENT-SOURCES.md` | ✅ done |
| 0.17 | Metapackage skeletons (dpkg) | `debos/packages/**` | 🟡 **hollow** — install a README and nothing else; not in the image |

**Gate (end of Phase 0):** PASS — but the gate itself was the problem. The old
`validate-phase0.py` only checked existence and syntax, so it reported PASS on an
unbuildable repository. The replacement, `validate-build.py`, checks pipeline
*semantics* and ships with `--self-test` to prove it can fail. Run both:

```bash
python3 scripts/validate-build.py --self-test
python3 scripts/validate-build.py --online
python3 scripts/validate-phase0.py
```

---

## Phase 1 — Foundry: build the ISO (the "make it real" phase)

Goal: a bootable ISO that passes a strict boot test, regardless of desktop polish.

| # | Task | Deliverable | Gate |
|---|------|-------------|------|
| 1.1 | Build driver + CI | `build/build-iso.sh`, `.github/workflows/build-iso.yml` | `build-iso` job green |
| 1.2 | Metapackages | `debos/packages/*/debian/` | ⚠️ hollow — real content is Phase 2 |
| 1.3 | First bootable ISO (daily) | `build/out/obsidian-daily-*.iso` | ✅ **done (2026-09-29)** — strict gate **PASS** under WHPX QEMU: all 5 required markers, both stock-Debian fingerprints absent, `flavor=daily` (commit `bdd660a`) |
| 1.4 | Ghost flavor boots | `obsidian-ghost-trixie-amd64.iso` | ✅ **done (2026-09-29)** — strict gate **PASS** under WHPX QEMU: `OBSIDIAN-OS-READY flavor=ghost` in 7.8 s, all 5 required markers, `ghost-amnesic: set`, `kernel-lockdown: 1` attested; sha256 `baf82be9…` |
| 1.5 | Encrypted install path | `debos/installer/` (calamares-flavored config) | ⬜ not started |
| 1.6 | Secure Boot + UKI + TPM2 | `scripts/boot-keys.sh` exists; **not wired into the image** | ⬜ not started |
| 1.7 | Hardened kernel in the image | `scripts/build-kernel.sh` exists; **orphaned** | ⬜ not started — image boots stock Debian kernel |

**Gate:** the `daily` and `ghost` matrix jobs produce ISOs, and the boot test
asserts on `OBSIDIAN-OS-MARKER` / `OBSIDIAN-OS-READY` plus per-subsystem
attestation (`sysctl-overlay`, `nftables-table`, `apparmor`, `aslr`, `firstboot`),
and **fails** if stock-Debian fingerprints appear.

> The previous gate asserted the serial marker `AEGIS-free obsidian.target
> reached`. That string was a leftover from the project's former name, and no
> component ever emitted it. It is gone.

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

## What is being done right now (this machine: Windows + WSL1, WHPX QEMU available)

**Current status: Phase 0 COMPLETE, Phase 1 FOUNDRY in progress.**

- Phase 0 deliverables 0.1–0.17 all exist; static gates green
  (`python3 scripts/validate-phase0.py`).
- **Phase 1 (daily) is DONE and boot-proven:** the ISO builds on this
  host (WSL1 + `mmdebstrap` + the OFD-lock shim from `docs/GAP-REPORT.md` §11) and
  passes the strict boot gate under WHPX QEMU — `OBSIDIAN-OS-READY` in ~7 s, all
  required markers present, both stock-Debian fingerprints absent, `flavor=daily`.
  Evidence: commit `bdd660a`, ISO `obsidian-daily-trixie-amd64.iso`
  (sha256 `fb818a9379ddca9778a59d41b30718c6023454fc06e11197d648a7b6ef7e2212`).
- **Phase 1 (ghost) is DONE and boot-proven:** `OBSIDIAN-OS-READY flavor=ghost`
  in 7.8 s on the same gate, `ghost-amnesic: set` + `kernel-lockdown: 1`
  attested. ISO `obsidian-ghost-trixie-amd64.iso`
  (sha256 `baf82be9dd3995b7764bd4492bbc87eb342170e70c7159657e1ba55c0bd69c75`).
- The CI pipeline (`.github/workflows/build-iso.yml`, `tests/boottest.sh`) exists
  and shares the marker file with the Windows runner, but has not yet been
  executed on GitHub; the local WHPX run is the current source of truth.

> The earlier claim that "offline ISO build is impossible / the moment the repo
> lands on GitHub, CI produces the first ISO" was wrong on this host: a full
> build and a hardware-accelerated boot test both run locally.
>
> **Stock-Debian negative control: DONE (2026-09-29).** The strict gate is
> proven to FAIL on the real, mirror-hash-verified
> `debian-live-13.7.0-amd64-standard.iso`: direct kernel+initrd boot with
> `console=ttyS0` forced produced `Debian GNU/Linux 13 debian ttyS0` →
> `debian login:` on serial (`FORBIDDEN 'Debian GNU/Linux'`) and no Obsidian
> markers (GAP-REPORT §14.5, commit `9f7c993`). The green runs are not a
> harness artifact.
>
> Next ticks:
> 1.5/1.6/1.7 (installer, Secure Boot + UKI, hardened kernel — both flavors'
> boot gates are now green)
> → Phase 2 desktop (the largest remaining gap, see `docs/GAP-REPORT.md` §2).