# Obsidian OS — Roadmap

> Milestones are outcome-driven (a gate that passes) not date-only. Calendar
> targets assume a full-time engineer; a small team halves each.

## M0 — Foundry scaffold (Phase 0) — *now*
**Gate:** this repository — spec, recipes, manifests, profiles, shell, scripts,
apps design, CI. Static validation green (yamllint, `sh -n`, `nft -c`, JSON/Rust
compiles).

## M1 — Bootable ISO (Phase 1)  ~weeks 2–6
- debos ISO builds on CI (daily flavor) from `obsidian.yaml`.
- `obsidian-core` metapackages resolve; first boot reaches `obsidian.target`,
  shell prompt opens in a terminal.
- QEMU serial-marker acceptance: firewall table loaded, securityctl answers,
  `pkg --version` works.
**Exit:** anyone on Earth runs the ISO on a VM and gets a console.

## M2 — Installer + encryption (Phase 1.4–1.5)  ~weeks 6–10
- Guided install: LUKS2 (Argon2id) root//home, TPM2 auto-unlock, Secure Boot keys
  enrollment, profile picker, first-boot wizard (language→privacy→profile→consent).
- Wipe/reinstall and dual-boot flows tested.
**Exit:** fresh install on bare metal with SB + LUKS2 + TPM2 works end-to-end.

## M3 — Desktop shell (Phase 2)  ~weeks 10–20
- ObsidianWM + panel: taskbar, tray, clock, Start+search, snap layouts, virtual
  desktops, themes. Files + Settings apps usable.
- XWayland/Wine runs a Windows app; low-end (lite) profile boots on 1 GB.
**Exit:** "desktop walkthrough" automated test passes; screenshots in docs.

## M4 — Security Center + Tools (Phase 3)  ~weeks 20–30
- `securityd` + GTK4 Security Center; consent ledger; tool registry driven by
  `manifests/tools.yaml`; firewall & IDS dashboards; Cells sandbox launcher.
- Pentester profile: install tools → per-tool consent → run inside Cells on the
  lab network; revocation kills running tools.
**Exit:** full red-team walkthrough in a sandboxed lab with reports generated.

## M5 — AI + Agents (Phase 4)  ~weeks 30–38
- `obsidian-ai` local-first (Ollama) + provider gateway; sidebar modes
  Chat/Agent/Plan with approval gate; agent orchestrator + 5 agents; Agent Hub +
  GitHub store.
**Exit:** "install me a PDF editor" works end-to-end; an OSINT agent produces a
report artifact.

## M6 — Ecosystem + one-click server (Phase 5)  ~weeks 38–46
- App Store; `pkg` full implementation; Server Hub roles; live-USB maker;
  updater + release signing.
**Exit:** beta ISO: signed, updatable, roles spin up in <2 min.

## M7 — Hardening audit (Phase 6)  ~weeks 46–52
- Run `docs/HARDENING.md` against beta ISO; publish CIS 1.0/1.1 evidence sheet;
  fix findings; optional third-party pentest.
**Exit:** hardening evidence report v1 + residual-risk note.

## M8 — 1.0 (Phase 6)  ~week 52+
- 1.0 ISO signed; LTS channel; upgrade path; privacy/legal pages final;
  community key ring.

## Long tail (post-1.0)
- SELinux alternative MAC; Arch-native flavor parity; 32-bit/i686 build;
  RISC-V/ARM (Pi/boxes) boards; Qubes-style VM set as default for Pentester 2.0;
  FIDO2/WebAuthn login; "Ghost hardware" mode for early boot anti-forensics;
  App Store curation review service (community).

## Theme: what defines DONE for the whole project
A **CNCF-style smoke**: fresh ISO → guided install (Pentester profile + consent)
→ QEMU lab walkthrough (recon→scan→exploit-lab→wireless→report) with every
action gated and audited — and the same ISO daily-driver walkthrough (start,
snap, virtual desktop, files, store install, AI ask). Both automated, both
recorded. That binary is the 1.0.