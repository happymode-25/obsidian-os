# Obsidian OS — Arch flavor ISO bridge

`debos/arch/obsidian-arch.yaml` produces a compreseed rootfs tar:

```
output/obsidian-arch-<flavor>-rootfs.tar.xz
```

That rootfs is the input to the **archiso** bridge that produces the bootable
ISO with the same Windows-feel session and the same boot menu (daily / ghost
amnesic live options).

## Build flow (CI: `build-iso-arch` job, mirrors build-iso.yml)

```
debos -t flavor:{daily,server,ghost,penta} debos/arch/obsidian-arch.yaml
     │
     ▼  rootfs tar.xz
mkarchiso -v -w /tmp/work archiso/profiles/obsidian/
     │
     ▼
obsidian-arch-<flavor>-<date>.iso   (systemd-boot UKI, Ventoy-compatible)
```

## What the archiso profile needs (in `archiso/profiles/obsidian/`)

- `profiledef.sh` — ISO name, arch, boot_mode: `uefi-x64.systemd-boot.esp`
  plus `bios` fallback.
- `packages.x86_64` — empty (rootfs already carries the tree); forces
  `mkarchiso` to use the `base/bootstrap` files copied from the rootfs tar
  (`airootfs/` populates from the tar).
- Ghost/amnesic: kernel cmdline `rd.live.overlay.overlayfs=1
  rd.systemd.firstboot=0` on the ghost boot entry + `airootfs_image_type
  squashfs`.

## Parity guarantee

Same **overlays** (`debos/overlays/*.tar`), same **profiles**
(`profiles/*.yaml`), same **scripts** (apply-profile / enable-services /
finalize / firstboot-wizard / pkg) — only the package backend differs
(`pacman` vs `apt`). Anything fixed on one side must be re-verified on the
other in CI (matrix key `base: [debian, arch]`).