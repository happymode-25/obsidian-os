# Task 1.7 handoff — hardened kernel packaging

State as of 2026-10-24. This document exists so the next person does not
re-derive the state from scratch or trust a stale "in progress" note.

## Goal

Ship an image whose kernel is built from Debian trixie's `linux` source plus the
Obsidian hardening fragment, versioned `LOCALVERSION=-obsidian-h`, and prove it
with the strict boot gate. Then add

```
required	OBSIDIAN-CHECK kernel-identity: obsidian-hardened
```

to `tests/boot-markers.conf`, in the same commit as the evidence.

## What is proven

- `scripts/build-kernel.sh` fetches Debian's `linux` source, merges
  `build/kernel/base-config-amd64.config` (the exact config from the stock
  trixie ISO's `/boot/config-*`) with
  `overlays/common/etc/obsidian/kernel/hardened.config`, and asserts every
  hardening symbol is present after `olddefconfig`. A missing symbol is a hard
  failure, not a warning. This ran successfully.
- The kernel and modules compile on the maintainer's host. Observed in the
  packaging log:

  ```
  Kernel: arch/x86/boot/bzImage is ready  (#1.obsidian)
  ```

- `build/build-iso.sh --kernel-deb` exists and enforces its own invariant: it
  refuses the flag unless `linux-image-amd64` is in the flavor's package set,
  installs the deb into the chroot, and fails the build if `dpkg -i` fails. It
  has **never** been run against a real hardened deb.

## What is not proven

- No `obsidian-linux-image-*.deb` has ever been produced.
- No ISO has ever contained the hardened kernel.
- The strict gate has never seen a `kernel-identity: obsidian-hardened` line, so
  that marker is deliberately not yet in `tests/boot-markers.conf`.
- The CI `build-kernel` job in `.github/workflows/build-iso.yml` has never run.
  It is wired (uploads the deb, the ISO job fails without it) but unexecuted.

## The blocker

`make bindeb-pkg` (Debian packaging around the kernel's own `debian/rules`)
stops late, after the image is linked, with:

```
make[4]: *** wait: No child processes.  Stop.
make[4]: *** Waiting for unfinished jobs....
```

Context from the failing run:

```
dpkg-buildpackage --build=binary --no-pre-clean --unsigned-changes \
  -R'make -f debian/rules' -j1 -a$(cat debian/arch) -d
dpkg-buildpackage: info: source package linux-upstream
dpkg-buildpackage: info: source version 6.12.107-1.obsidian
...
Kernel: arch/x86/boot/bzImage is ready  (#1.obsidian)
make[4]: *** wait: No child processes.  Stop.
```

### Ruled out

- **Missing `debhelper`.** This was the earlier failure (`dh_listpackages:
  command not found`). Fixed: `debhelper` is now installed by
  `scripts/build-kernel.sh` and the packaging proceeds past it.
- **Two builds racing.** A stale autopilot could relaunch builds; it was
  excluded while reproducing this failure.
- **Discarded output.** `bindeb-pkg` output is now captured to
  `$BPKG_LOG` (default `/root/bindeb-pkg.console.log`) and its tail is printed
  on failure. The failure above is from a captured log, not a guess.

### Suspected, not confirmed

The host is **WSL1** (Ubuntu 24.04; `rootfs on / type wslfs`) on 8 cores /
16 GB RAM. WSL1 emulates Linux process semantics on top of Windows, and
`wait: No child processes` is a process-management error, not a compiler error.
Two candidates, neither verified:

1. WSL1's fork/wait emulation losing a child during the heavily parallel
   Debian packaging phase.
2. Resource exhaustion while Windows was already near zero free RAM (observed:
   0.5 GB free of 15.9 GB with a local inference server running).

A WSL1→WSL2 conversion was attempted to remove candidate 1 and did not complete:
`Wsl/Service/CreateVm/0x800705b4` (VM start timeout) while the host was out of
RAM. The distro was left intact on WSL1. Retrying that conversion after freeing
memory is reasonable, but it is not the only path.

Do not record either candidate as the cause without a log that shows it.

## Fastest ways to finish

### 1. CI (no local hardware)

```bash
gh workflow run build-iso.yml -f flavor=daily
gh run watch
```

`build-kernel` has a 240-minute timeout on a 4-core runner; the full Debian
kernel build plus packaging may exceed that. If it times out, raise the timeout
in the workflow — do not reduce what the kernel builds. Attach the failing step's
log to the tracking issue either way.

### 2. Native Linux / WSL2 host

```bash
sudo KERNEL_BUILD=/var/tmp/kernel-build ./scripts/build-kernel.sh
```

The persistent tree resumes: a re-run re-verifies `.config`, skips the merge, and
lets `make` rebuild only what is missing. Expect several hours for a cold build,
much less for a resume that only has to finish packaging.

Single-build discipline: never let two runs share `KERNEL_BUILD`. Parallelism
comes from `KBUILD_JOBS`, not from a second process.

### 3. Continue on the existing WSL1 host

The tree at `/root/kernel-build` is complete up to the packaging step. Re-running
the script there resumes rather than recompiling. Start from the captured
`/root/bindeb-pkg.console.log`, and try `KBUILD_JOBS=4` (or even 2) for the
packaging phase to test the WSL1 fork/wait hypothesis.

## Verification checklist

- [ ] `dpkg-deb -I build/kernel-out/obsidian-linux-image-*.deb` shows version
      `6.12.107-1.obsidian` (or the current source version).
- [ ] `dpkg-deb -c` shows `boot/vmlinuz-*obsidian*` and a populated
      `lib/modules/*obsidian*/`.
- [ ] Inside the built image, `uname -r` contains `obsidian-h`.
- [ ] ISO built with `--kernel-deb` and the build log shows the deb installed
      into the chroot replacing `linux-image-amd64`.
- [ ] `tests/boottest.sh` (or `-win.ps1`) passes with all required markers and no
      forbidden Debian strings.
- [ ] `OBSIDIAN-CHECK kernel-identity: obsidian-hardened` is actually present in
      the console output.
- [ ] Only then: flip the marker to `required`, re-run the gate, commit both
      together.

## Do not

- Do not add `kernel-identity` as `required` before an image passes with it.
- Do not build the ISO with the stock kernel and describe it as hardened.
- Do not remove the forbidden `Welcome to Debian` / `Debian GNU/Linux` markers.
- Do not commit the `.deb`, the ISO, or the build tree.
