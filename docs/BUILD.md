# Obsidian OS — Build Guide

The build pipeline is `build/build-iso.sh`: a plain, debuggable shell pipeline
with no container and no image framework.

```
debootstrap  ->  install real packages  ->  apply overlays  ->  enable units
             ->  update-initramfs        ->  mksquashfs     ->  grub-mkrescue
```

It replaces `debos/obsidian.yaml`, which could not build at all. If you are
looking for why, read [`GAP-REPORT.md`](GAP-REPORT.md) — the short version is
that the recipe used a debos action that no longer exists, its `run` actions all
executed on the build host instead of the image, and the boot test could not
distinguish the result from stock Debian.

---

## 1. Requirements

Build host (Debian or Ubuntu, **root** required):

| Tool | Debian/Ubuntu package |
|---|---|
| `debootstrap` | `debootstrap` |
| suite signature keyring | `debian-archive-keyring` |
| squashfs | `squashfs-tools` |
| ISO + bootloader | `xorriso`, `mtools`, `dosfstools`, `grub2-common`, `grub-pc-bin`, `grub-efi-amd64-bin` |
| unit management | `systemd` (for `systemctl --root`) |

```bash
sudo apt-get install -y debootstrap debian-archive-keyring squashfs-tools \
  xorriso mtools dosfstools grub2-common grub-pc-bin grub-efi-amd64-bin systemd
```

> `debian-archive-keyring` is not optional. Without it debootstrap cannot verify
> the suite's `Release` signature and aborts with *"Failed getting release
> file"*. The tempting workaround, `--no-check-gpg`, would disable signature
> verification on the base image of a hardened distro. Install the keyring.

To boot-test the result: `qemu-system-x86`.

## 2. Build

```bash
sudo ./build/build-iso.sh --flavor daily
```

| Flag | Default | Notes |
|---|---|---|
| `--flavor` | *required* | `daily`, `developer`, `pentester`, `server`, `ghost` |
| `--suite` | `trixie` | any suite `debootstrap` supports |
| `--arch` | `amd64` | |
| `--mirror` | `https://deb.debian.org/debian` | |
| `--keep-chroot` | off | keep the tree on failure for debugging |
| `--jobs` | `nproc` | squashfs threads |

Output lands in `build/out/obsidian-<flavor>-<suite>-<arch>.iso`, BIOS + UEFI
hybrid, built with `grub-mkrescue`.

Roughly 10–20 minutes and ~4 GB of disk per flavor.

## 3. How a flavor is defined

A flavor is two files, and nothing else:

- **`build/flavors/<flavor>.pkgs`** — extra packages on top of `common.pkgs`.
- **`overlays/<flavor>/`** — optional files copied into the image root.

`build/flavors/common.pkgs` applies to every flavor and is where the base system
lives. `overlays/common/` likewise.

A flavor can also carry `overlays/<flavor>/etc/obsidian/<flavor>/cmdline.extra`,
one kernel flag per line. The build driver appends it to the generated
`grub.cfg` `linux` line. This is how Ghost gets `overlay=tmpfs` and
`lockdown=confidentiality` without touching the common config.

To add a flavor: create the `.pkgs` file, optionally the overlay dir, and add it
to the `validate` matrix in `.github/workflows/build-iso.yml`.
`validate-build.py` check 7 fails if CI builds a flavor with no `.pkgs` file.

## 4. Boot test

```bash
bash tests/boottest.sh build/out/obsidian-daily-trixie-amd64.iso \
  --flavor daily --timeout 600
```

The test boots the ISO under QEMU with `-accel tcg`, captures the serial console,
and requires `OBSIDIAN-OS-READY`. That string is emitted only by
`overlays/common/usr/local/sbin/obsidian-boot-report`, which runs as
`obsidian-boot-report.service` and attests that the hardening actually took
effect:

```
OBSIDIAN-OS-MARKER v1 flavor=daily build=trixie/amd64 host=obsidian-daily
OBSIDIAN-CHECK sysctl-overlay: present
OBSIDIAN-CHECK nftables-table: loaded
OBSIDIAN-CHECK apparmor: Y
OBSIDIAN-CHECK aslr: 2
OBSIDIAN-CHECK firstboot: ready
OBSIDIAN-OS-READY flavor=daily
```

It **fails** if the log contains `Welcome to Debian` or `Debian GNU/Linux` —
those are the fingerprints of the old `debian-live` substitution, where the
build "succeeded" by shipping a vanilla image.

There is no soft mode. The previous test had one, and its success patterns
(`login:`, `Reached target`, `tty[S0-9]`) are all printed by stock Debian, so it
passed on a broken image. `validate-build.py` rejects the reintroduction of
`BOOTTEST_SOFT` in the test or in CI.

## 5. Validation gates

Two scripts, and they answer different questions.

```bash
python3 scripts/validate-build.py --self-test   # proves the gate can fail
python3 scripts/validate-build.py --online      # semantic checks + package index
python3 scripts/validate-phase0.py              # deliverables exist and parse
```

`validate-phase0.py` checks **existence and syntax**. It is not sufficient and was
never sufficient — it printed `GATE: PASS` on a repo whose recipe could not
build.

`validate-build.py` checks **meaning**: debos action vocabulary against upstream,
`chroot: true` on every `run` action, boot-test strictness, CI artifact
reachability, kernel variable drift, systemd unit references, package names
against the real suite index, and build-driver self-consistency.

Run `--self-test` before trusting it. It feeds the validator deliberately broken
fixtures and asserts each is rejected. A gate never observed failing is the
problem it was written to fix.

## 6. Build host notes

Things that will cost you time otherwise.

**Do not build on `/mnt/c` (DrvFs).** `debootstrap` and `mksquashfs` need real
symlinks, device nodes, and ownership. Copy the tree onto the native filesystem
first:

```bash
tar -C /mnt/c/path/to/obsidian-os --exclude=.git --exclude=build/work -cf - . \
  | tar -C /root/obsidian-os -xf -
cd /root/obsidian-os && sudo ./build/build-iso.sh --flavor daily
```

**WSL2 vs WSL1.** WSL2 needs the *Virtual Machine Platform* Windows optional
feature; without it `wsl --import --version 2` fails with
`HCS_E_HYPERV_NOT_INSTALLED`. That is not a firmware problem — if VBS/HVCI is
already running, VT-x works. Run `tools/enable-wsl2.ps1` as Administrator and
reboot.

WSL1 works for this build (`mount -t proc`, `mount --bind`, and `chroot` all
function, which is all `debootstrap` needs), with two caveats:

- It ships IPv6-only resolvers (`fec0:...`) that are unreachable. Write a real
  `/etc/resolv.conf`, and set `Acquire::ForceIPv4 "true"` in
  `/etc/apt/apt.conf.d/` or every fetch stalls on AAAA lookups.
- Installing the `systemd` package makes `systemd-resolved` symlink
  `/etc/resolv.conf` to `/run/systemd/resolve/stub-resolv.conf`. systemd does
  not run under WSL1, so that target never exists and **all name resolution
  fails with no obvious cause**. Replace the symlink with a real file and mask
  `systemd-resolved.service`.

**QEMU acceleration.** On a host without VT-x exposed to the guest, use
`-accel tcg`. The boot test already does.

## 7. Reproducibility

`SOURCE_DATE_EPOCH` defaults to a fixed value and the chroot's `/etc/machine-id`
is emptied, so two builds of the same commit produce equivalent trees. This is
*approximate* reproducibility: it does not pin the package versions pulled from
the mirror. Exact pinning is a `snapshot.debian.org` change and is tracked in the
roadmap.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Failed getting release file` | no suite keyring | install `debian-archive-keyring` |
| `Temporary failure resolving` | WSL1 `resolv.conf` is a dangling symlink | §6 |
| `unknown debos action` in a log | a stale recipe is still being invoked | recipes were removed; check you are running `build/build-iso.sh` |
| ISO drops to GRUB rescue prompt | `grub.cfg` not at `boot/grub/grub.cfg` | `validate-build.py` check 7 catches this |
| Boot test: no `OBSIDIAN-OS-MARKER` | kernel never reached multi-user | read the serial log with `--keep-log`; likely a missing `live-boot` |
| `could not enable <unit>` | unit not in the image | `validate-build.py` check 5 catches this before the build |
| Guest has no network | firewall `input` policy drop without a DHCP accept | see the ordering rules in `overlays/common/etc/nftables.conf` |
