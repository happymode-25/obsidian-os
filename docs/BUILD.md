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
| **bootstrapper (preferred)** | **`mmdebstrap`** — see below, do not start with `debootstrap` |
| fallback bootstrapper | `debootstrap` |
| suite signature keyring | `debian-archive-keyring` |
| squashfs | `squashfs-tools` |
| ISO + bootloader | `xorriso`, `mtools`, `dosfstools`, `grub2-common`, `grub-pc-bin`, `grub-efi-amd64-bin` |
| unit management | `systemd` (for `systemctl --root`) |
| C compiler | `gcc` or `cc` — **only needed on a host that lacks OFD locks** (WSL1); see §6.1 |

```bash
sudo apt-get install -y mmdebstrap debian-archive-keyring squashfs-tools \
  xorriso mtools dosfstools grub2-common grub-pc-bin grub-efi-amd64-bin systemd
```

> **Use `mmdebstrap`, not `debootstrap`.** `debootstrap` fetches every `.deb`
> with a single serial `wget` running GNU wget's default timeouts
> (`--dns-timeout=900 --connect-timeout=900 --tries=20`). On any host whose
> network accepts a connection and then stalls, one package blocks the whole
> bootstrap for 15 minutes, and it downloads sequentially, so a fast link is
> wasted. Measured on the WSL1 host this was written for: `debootstrap` managed
> 10 packages in 20 minutes; `mmdebstrap` did the same job in 754s.
> `debootstrap` remains a supported fallback and is still listed above.

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

**The "stalled" phase is a kernel download, not a hang.** After the base packages
are configured, apt downloads `linux-image-*` (tens of MB) before installing the
remaining packages. `dpkg.log` goes quiet for many minutes during this, and on a
slow line the file visibly crawls — on the reference host it transferred at
~200 KB/s and looked dead for over six minutes. Before killing the build, check
that the transfer is actually progressing rather than that nothing has been
written:

```sh
ls -l build/work/chroot/var/cache/apt/archives/partial/
# watch the .deb grow; if it is growing, it is downloading
```

Host load (not busy) + no `dpkg`/`apt` child + one socket held by the `https`
method is the fingerprint of this phase, not of a deadlock.

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

The test boots the ISO under QEMU, captures the serial console, and requires
`OBSIDIAN-OS-READY`. Acceleration is probed, not assumed: `boottest.sh` tries KVM
and falls back to TCG, `boottest-win.ps1` tries WHpx and falls back to TCG. Pass
`--accel` / `-Accel` to pin one. That string is emitted only by
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

WSL1 works for this build, with three caveats. The first two are network and
name-resolution traps; the third stops the build outright.

- It ships IPv6-only resolvers (`fec0:...`) that are unreachable. Write a real
  `/etc/resolv.conf`, and set `Acquire::ForceIPv4 "true"` in
  `/etc/apt/apt.conf.d/` or every fetch stalls on AAAA lookups.
- Installing the `systemd` package makes `systemd-resolved` symlink
  `/etc/resolv.conf` to `/run/systemd/resolve/stub-resolv.conf`. systemd does
  not run under WSL1, so that target never exists and **all name resolution
  fails with no obvious cause**. Replace the symlink with a real file and mask
  `systemd-resolved.service`.

### 6.1 WSL1 cannot lock `/etc/passwd` — and the build handles it

WSL1's kernel emulation does not implement open-file-description locks
(`F_OFD_SETLK`, Linux 3.15+). Measured on this host:

| lock API | wslfs | tmpfs |
|---|---|---|
| `flock(2)` | OK | OK |
| `fcntl(F_SETLK)` | OK | OK |
| `fcntl(F_OFD_SETLK)` | **EINVAL** | **EINVAL** |

Because tmpfs fails identically, no mount arrangement works around it: it is a
missing kernel feature, not a filesystem property. `systemd-sysusers` takes an
OFD lock on `/etc/passwd`, and it runs from systemd's postinst, so **every**
systemd package fails to configure:

```
Failed to take /etc/passwd lock: Invalid argument
dpkg: error processing package systemd (--configure)
```

The build detects this with a **capability probe**, not a hostname check, and
only then compiles `build/wsl1-ofd-lock-shim.c` and injects it through an
mmdebstrap setup hook. A normal Linux build host — and WSL2 — never compiles or
installs any of it.

The shim supplies the missing lock acquisition only. The package's own
maintainer script then runs and performs its real work, so the users systemd
creates are genuine, not synthesised. The shim is removed by an mmdebstrap
customize hook, and `build-iso.sh` then *asserts* it is absent from the image
before continuing: shipping it would preload a lock-stub into every process on
first boot, including anything the user installs later.

If you ever see `Failed to take /etc/passwd lock` from this build, the probe
reached the wrong verdict — that is the thing to look at, not the package.
`scripts/validate-build.py` and `docs/GAP-REPORT.md` §11 record the full
diagnosis, including the two wrong turns on the way (suspecting `flock`, and
reading an `objdump` that turned out not to be installed).

### 6.2 `Cannot allocate memory` mid-bootstrap is the host, not the image

This one is worth writing down because the message points at the wrong thing:

```
Creating user 'systemd-network' (systemd Network Management) with UID 998 and GID 998.
Failed to backup /etc/group: Cannot allocate memory
dpkg: error processing package systemd (--configure)
```

`useradd` cannot allocate memory while backing up a file the size of
`/etc/group`. That is not a `useradd` bug and not a broken image — the process
simply had nothing left to be given. It shows up during the busiest part of the
build, when ~155 MB has just been downloaded and 128 packages are being
configured, so it reads like a build fault.

**Check `free -m` before believing it.** On the reference host the failing run
showed 15,940 MB of 16,259 MB used and **318 MB available**, with 44 GB of swap
untouched — WSL1 reports the host's memory, so the whole ceiling is the host's.

Two things worth knowing:

- The available figure is **volatile**. The same host measured 0.07 GB free and
  5.6 GB free minutes apart. Before concluding the build is broken, re-measure.
- `vmmemWSL` will show a very large *private commit* (measured ~4.9 GB) with a
  small *working set*. That is WSL1's own reservation for the page cache and
  the build tree, not the build's live footprint. Reading it as live usage is
  what makes it look unrecoverable.
- **`used` is Windows, not the build.** WSL1 has no VM: it translates syscalls,
  and `free` reads host-wide memory counters. On the failing host, `free`
  reported 9.3 GB used while the sum of RSS across every process inside WSL was
  a few MB. So the pressure is the Windows desktop's own, and nothing the build
  does can reclaim it — nor should the build try. Confirm with:

  ```bash
  ps -eo rss --no-headers | awk '{s+=$1} END {printf "%.1f GB\n", s/1048576}'
  ```

  If that is small while `used` is large, the only real remedy is to close
  Windows applications. Do not kill the user's processes to make room.

If it still fails with several GB free, the next thing to check is whether the
build is being run on `/mnt/c` — see the note above.

**QEMU acceleration.** Do not hardcode `-accel`. Both boot tests probe for a
hardware accelerator and fall back to TCG, because TCG emulates the CPU and a
cold boot of a freshly built live image under TCG can take many minutes — long
enough to blow the timeout on an otherwise healthy build, which is a failure
mode that looks like a broken image. Neither test infers availability from a
device node or from `qemu -accel help`: the first can exist without permission
or a hypervisor behind it, and the second lists what the *binary* was built
with, not what the host supports. Both start a real `pc` machine with no boot
media and check whether QEMU survives. Note the spelling is `whpx`, not
`wphx`; the typo fails closed into TCG, which presents as a passing-but-slow
gate rather than an error.

### 6.3 Operational failures from the first real builds

The build host is WSL1 on a shared-desktop Windows machine. Three failures that
looked like build defects were actually environment, and each cost a full
bootstrap (~10 minutes) to discover:

**A dangling `resolv.conf` symlink kills the first post-bootstrap step.**
`mmdebstrap` leaves the chroot's `/etc/resolv.conf` as a symlink to
`../run/systemd/resolve/stub-resolv.conf` — a target that does not exist inside
the build tree. The guard "copy the host resolv.conf in if the chroot's lacks a
`nameserver` line" is *satisfied* by a dangling link (grep silently fails
through it), so the copy runs, and GNU `cp` refuses to write through a dangling
symlink:

```
cp: not writing through dangling symlink '.../build/work/chroot/etc/resolv.conf'
ISO_MISSING (rc=1)
```

Fixed in `build/build-iso.sh` by removing the symlink before copying. The rule
it teaches: this failure mode only shows up *after* a successful bootstrap, so
no amount of pre-verification of the script catches it — the chroot must be
tested with a real bootstrap.

**A throttled mirror, not a slow build.** On this host, `deb.debian.org`
(https and http) and `ftp.debian.org` all delivered ~87 KB/s for a 5 MiB range,
while `mirrors.kernel.org` delivered 2.3 MB/s for the same file. The kernel
`.deb` (`linux-image-6.12.107+deb13-amd64`) is ~108 MB, so at the throttled
rate the "installing remaining packages" phase takes 20+ minutes at best and
apt's real rate collapsed to single-digit KB/s — indistinguishable short-term
from the apparent stall in §2. Measure the actual throughput before waiting it
out; apt verifies package hashes, so mirror choice is safe. The build driver
takes `--mirror <url>` (`build/build-iso.sh`); the reference builds use
`http://mirrors.kernel.org/debian`.

**A detached build does not survive a host restart.** `launch-build.sh` uses
`setsid nohup ... &` so the build survives the invoking shell dying — but not a
Windows/WSL restart, which kills every WSL process regardless of `setsid`. After
a host restart the build is found dead mid-bootstrap with **no error markers**
(the log just stops). Check process state, not the log tail, before diagnosing;
then relaunch with the same mirror override — preflight cleanup discards the
dead run's tree automatically.

**Relaunching also discards a finished ISO.** The launcher stages a fresh
`/root/obsidian-os` on every run (`rm -rf` + re-tar), so an ISO sitting in the
*old* tree's `build/out` is deleted the moment a new build starts. Never run
`collect-iso.sh` concurrently with a relaunch: copy the ISO to the Windows side
(and verify the hash) *before* launching the next build.

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
