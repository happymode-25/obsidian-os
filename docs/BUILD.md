# Obsidian OS — Build Instructions

Builds the Obsidian OS ISO from this repository on a Linux host (native or WSL2).
CI equivalent in `.github/workflows/build-iso.yml`.

---

## 1. Host prerequisites

- **OS:** Debian 12/13 (or Ubuntu 24.04+), x86_64. WSL2 (Debian/Ubuntu distro)
  works with the same commands.
- **Tools:**
  - `debos` ≥ 1.1.14 (the only real requirement; provides `debian-live`)
  - `qemu-utils` (live ISO packaging, disk images)
  - `whois` (used by live-build for `mkpasswd` preseed hashes)
  - `git`, `tar`
- **Disk:** ~15 GB free. **Network:** Debian mirrors + GitHub.

```bash
sudo apt update
sudo apt install -y debos qemu-utils whois git tar
```

> WSL2 note: run debos from inside the WSL distro, not through the Windows
> PowerShell; keep the tree under `~/` (not `/mnt/c`) so filesystem semantics
> are native and fast.

## 2. Build the ISO

```bash
git clone https://github.com/YOUR-ORG/obsidian-os
cd obsidian-os

# Daily Driver base ISO
debos -t flavor:daily debos/obsidian.yaml

# Other flavors
debos -t flavor:penta  debos/obsidian.yaml   # Pentester (tools still consent-gated)
debos -t flavor:server debos/obsidian.yaml   # Headless server
debos -t flavor:ghost  debos/obsidian.yaml   # Privacy-Max (amnesic live)
```

Output lands in `output/`:

```
output/obsidian-daily-trixie-amd64.iso
output/obsidian-penta-trixie-amd64.iso
...
```

Optional recipe variables (when not using a profile flavor):

```bash
debos -t flavor:daily -t arch:amd64 -t release:trixie debos/obsidian.yaml
```

Dry-run parse check (no root, no build):

```bash
debos --dry-run -t flavor:daily debos/obsidian.yaml
```

## 3. Verify the ISO boots (QEMU smoke test)

```bash
sudo apt install -y qemu-system-x86
bash tests/boottest.sh output/obsidian-daily-trixie-amd64.iso "obsidian.target reached" 240
```

`tests/boottest.sh` boots the ISO headless, captures the serial console to a log,
and exits 0 when the configured marker appears (default `obsidian.target
reached`), 1 on timeout. Expected before that marker:

- firewall table loaded (`nft -c` result logged at boot)
- `securityctl status` answers (posture reflects the flavor)
- shell prompt readable on the login console

Interactive check (desktop):

```bash
qemu-system-x86_64 -m 4096 -enable-kvm -cdrom output/obsidian-daily-trixie-amd64.iso
```

## 4. Building the obsidian-* metapackages

The recipe installs `obsidian-core`, `obsidianwm`, `obsidian-panel`,
`obsidian-apps`, … from a local Debian repo. Skeleton packages live in
`debos/packages/*/debian/` — build them on any Debian host:

```bash
# once: seed a local repo the CI uses
for p in debos/packages/*/; do
  (cd "$p" && dpkg-buildpackage -b -us -uc)
done
# then serve debos/packages/*.deb via an apt repo (apt-ftparchive) or put them
# in the debos image list directly.
```

CI does this automatically (`.github/workflows/build-iso.yml`, step `build-packages`).

## 5. Custom hardened kernel

The intent is `linux-hardened` features on Debian's `linux-image-amd64`. Two paths:

- **Simplest (recommended, CI):** a patched source build job
  (`obsidian-kernel` package) wired into the CI pipeline from an upstream
  `linux` tree + the Arch `linux-hardened` config patches, cross-checked against
  `docs/HARDENING.md` (lockdown, hardened allocator, INIT_ON_ALLOC/FREE, …).
- **Fast prototype:** use the Arch flavor instead (`debos -t arch` → repo)
  which ships `linux-hardened` ready-built; Debian ISO can pin
  `linux-image-6.x-oby-hardened` once the job lands.

## 6. Secure Boot keys + UKI (install-time)

The ISO boots via systemd-boot + UKI. On first *guided install*:

```bash
# inside the installed system (post-install helper, outline)
sbctl create-keys
sbctl enroll-keys --microsoft
sbctl sign /usr/lib/systemd/boot/efi/systemd-bootx64.efi
sbctl sign /boot/EFI/Linux/obsidian.efi        # the UKI
systemd-cryptenroll --tpm2-device=auto /dev/<root-luks>   # optional TPM2 unlock
```

Full recipe + measured-boot notes are tracked as Phase 1.5 tasks
(`docs/ROADMAP.md` M2).

## 7. Alternative build path: live-build

If debos actions ever block on thin clients, the same overlays can be packed by
`live-build`:

```bash
sudo apt install -y live-build debootstrap
lb config --distribution trixie --binary-images iso-hybrid \
          --bootappend-live "boot=live components quiet"
# point debian/ and chroot hooks at debos/overlays-src/common etc.
lb build
```

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `debos: unknown action debian-live` | debos ≥ 1.1.14 (or build debos from source) |
| `apt-get update` fails inside build | host DNS/network; retry with a Debian mirror override (`-t mirror:...`) |
| QEMU boot hangs before marker | add `-t` QEMU accel arg in `tests/boottest.sh`; check CPU virtualization is available or use `-accel tcg` |
| Overlay unpack fails | regenerate `debos/overlays/*.tar` with `scripts/make-overlays.sh` |
| Sandbox/KVM errors in Penta profile | ensure KVM group on host (`sudo usermod -aG kvm $USER`) — cells need `/dev/kvm` |
| ISO too small / packages missing | likely obsidian-* repo empty — build metapackages (§4) first |

## 9. CI

Push a `v*` tag (or run `workflow_dispatch`) and GitHub Actions builds the same
flavors in containers and uploads the ISOs to the release:
`.github/workflows/build-iso.yml`.