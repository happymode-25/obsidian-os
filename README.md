# Obsidian OS — a Windows-feel Linux, hardened by default

> **One-liner:** A custom Linux distribution whose desktop is a Windows 11 clone
> (taskbar, Start, tray, Explorer, snap layouts, virtual desktops), whose shell is
> a unified Bash/PowerShell hybrid, and whose default posture is hardened +
> anti-forensic + AI-assisted, with a full pentest suite behind a consent wall.

---

## Read this first

**The desktop does not exist yet.** The architecture, security posture, shell
design, and app designs are specified and the base OS builds and boots, but there
is no window manager, no panel, and no applications. The `obsidian-*` metapackages
under `debos/packages/` are empty skeletons that install a README and nothing
else. Treat the Windows 11 look as a Phase 2 deliverable, not a feature of this
tree.

**Phase 0 was previously reported complete and was not.** The ISO recipe could not
build, its build steps ran on the wrong machine, and the boot test could not tell
the project's own image apart from stock Debian. All of it is documented, with
evidence, in **[`docs/GAP-REPORT.md`](docs/GAP-REPORT.md)**. Read that before
trusting any status claim in this repository, including the ones here.

---

## What actually works today

| | |
|---|---|
| Builds a bootable ISO | yes — `build/build-iso.sh`, BIOS + UEFI hybrid |
| Boots and passes a strict test | yes — asserts on a marker stock Debian cannot emit |
| Hardening applied and attested at boot | yes — sysctl, nftables, AppArmor, ASLR, zram |
| Ghost (amnesic) flavor | yes — volatile journal, tmpfs overlay, shutdown residue reduction |
| Five flavors defined | yes — `daily`, `developer`, `pentester`, `server`, `ghost` |
| CI builds and boot-tests on tag | yes — `.github/workflows/build-iso.yml` |
| **Desktop shell / WM / panel / apps** | **no — not built** |
| **Hardened custom kernel in the image** | **no — stock Debian kernel** |
| **Pentest tooling** | **not installed by design; see `docs/LEGAL.md`** |
| **`tools.yaml` URLs** | **~13 fabricated; not yet corrected** |

---

## What you are looking at

| Path | What it is |
|------|-----------|
| **[`docs/GAP-REPORT.md`](docs/GAP-REPORT.md)** | **What was broken, how it was verified, what was fixed** |
| `docs/ARCHITECTURE.md` | Architecture spec (kernel, base, init, DE, security layers) |
| `docs/BUILD.md` | **Build guide — read this to build an ISO** |
| `docs/ADR-0001-debos-replacement.md` | **Why debos and the Arch base were dropped** |
| `docs/COMPONENT-SOURCES.md` | Upstream open-source map, by layer |
| `docs/UNIFIED-SHELL.md` | Windows/macOS/Linux unified shell spec + translation tables |
| `docs/APPS.md` | Security Center + AI Assistant design |
| `docs/HARDENING.md` | Hardening checklist mapped to the CIS Debian Benchmark |
| `docs/ROADMAP.md` | MVP → Beta → 1.0 milestone plan |
| `docs/LEGAL.md` | Ethical/legal guardrails (tools disabled by default, consent gating) |
| `build/build-iso.sh` | The build driver: mmdebstrap → packages → overlays → squashfs → ISO |
| `build/flavors/*.pkgs` | Per-flavor package lists (the entire flavor definition) |
| `overlays/common/` | Hardening applied to every image: sysctl, nftables, AppArmor, boot attestation |
| `overlays/ghost/` | Ghost flavor: volatile journal, Tor-only egress, shutdown residue reduction |
| `tests/boottest.sh` | Strict QEMU boot test — no soft mode |
| `scripts/validate-build.py` | Semantic gate: the checks that actually catch pipeline bugs |
| `manifests/tools.yaml` | Tool integration manifest (**partly unverified**) |
| `profiles/*.yaml` | Daily Driver / Developer / Pentester / Server / Privacy-Max |
| `shell/` | Unified shell: PowerShell 7 profile + bash aliases |
| `scripts/pkg` | `pkg` unified package manager wrapper |
| `scripts/firstboot-wizard` | First-boot setup (language / privacy / profile) |
| `debos/installer/` | Calamares guided installer config (LUKS2, Secure Boot) |
| `tools/enable-wsl2.ps1` | One-shot host setup to enable WSL2 |

---

## Build it yourself

```bash
sudo apt-get install -y debootstrap debian-archive-keyring squashfs-tools \
  xorriso mtools dosfstools grub2-common grub-pc-bin grub-efi-amd64-bin systemd

git clone https://github.com/happymode-25/obsidian-os
cd obsidian-os
sudo ./build/build-iso.sh --flavor daily
# → build/out/obsidian-daily-trixie-amd64.iso

bash tests/boottest.sh build/out/obsidian-daily-trixie-amd64.iso --flavor daily
```

Full instructions, WSL notes, and troubleshooting: **[`docs/BUILD.md`](docs/BUILD.md)**.

## Validate it

```bash
python3 scripts/validate-build.py --self-test   # prove the gate can fail
python3 scripts/validate-build.py --online      # semantic checks + package index
python3 scripts/validate-phase0.py              # deliverables exist and parse
```

`validate-phase0.py` only checks that files exist and parse. It is not the gate
that matters. `validate-build.py` is — and `--self-test` verifies it by feeding
it deliberately broken fixtures.

---

## Headline design decisions

1. **Base:** Debian trixie, single base image. An earlier "Debian + Arch dual
   base" was dropped: there is no such hybrid base image, and the Arch recipe was
   broken in exactly the same way as the Debian one. Rationale in
   `docs/GAP-REPORT.md` §5.
2. **Init:** systemd.
3. **Look (planned, Phase 2):** KDE Plasma 6 reshaped into a Windows 11 layout as
   the fast path; ObsidianWM (a labwc/wlroots fork) as the long-term custom path.
   Neither is implemented.
4. **Shell:** Bash as the native engine, PowerShell 7 as the Windows-compat layer,
   with a translation layer so `dir`, `copy`, `Get-Process` work in both prompts.
5. **Security posture** (per profile): `Standard` → `Hardened` → `Ghost`
   (anti-forensic). Ghost's threat model is stated honestly in
   `overlays/ghost/README.md`: it defeats disk and swap forensics, **not** RAM
   acquisition from an adversary with physical access.
6. **Pentest tools ship disabled** and are activated only under the Pentester
   profile after an explicit authorization consent step. See `docs/LEGAL.md`.
7. **AI:** local-first (Ollama) with a provider abstraction; terminal execution
   requires explicit approval. Designed, not built.

---

> **Legal.** This project ships offensive/dual-use tooling *disabled* and gated by
> an authorization-consent flow. Read `docs/LEGAL.md` before enabling the Pentester
> profile. Use only against systems you own or are authorized to test.
