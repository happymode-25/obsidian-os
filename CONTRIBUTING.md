# Contributing to Obsidian OS

Thanks for looking. This project is a hardened Debian-based distribution that is
partly built and booting, and it has one hard blocker left before Phase 1 can be
called done: **the hardened kernel is compiled but never got packaged into a
`.deb`, so no image has ever shipped it.**

Everything needed to finish that is in this repository. What it needs is a
machine with more headroom than the maintainer's, or a GitHub Actions run.

Read [`docs/GAP-REPORT.md`](docs/GAP-REPORT.md) first. This project has a history
of "complete" status claims that were not true, so the rule here is: **no claim
without a log, a checksum, or a green gate.** That rule applies to your PR too.

---

## The one thing that unblocks Phase 1: Task 1.7

`scripts/build-kernel.sh` builds a kernel from the Debian trixie `linux` source
using the exact config Debian ships (`build/kernel/base-config-amd64.config`)
plus the Obsidian hardening fragment, and packages it with
`LOCALVERSION=-obsidian-h` so that `uname -r` contains `obsidian`.

Status, precisely:

| Step | State |
|---|---|
| Fetch source, merge config, verify every hardening option | works (hard-fails if an option did not apply) |
| Compile kernel + modules | completes (`arch/x86/boot/bzImage is ready`) |
| `make bindeb-pkg` → `obsidian-linux-image-*.deb` | **not yet completed on the maintainer's host** |
| Build ISO with `--kernel-deb` | wired, never run against a real hardened deb |
| Strict boot gate on a hardened ISO | never passed |
| `kernel-identity: obsidian-hardened` in `tests/boot-markers.conf` | still unset on purpose; it is flipped in the commit that proves it |

The local build host is WSL1 on a 16 GB / 8-core box. Packaging dies late in
`make -f debian/rules binary` with `make[4]: *** wait: No child processes. Stop.`
after the kernel image is linked. That is the open bug. The console log the
script now writes (`$KERNEL_BUILD/../bindeb-pkg.console.log`, default
`/root/bindeb-pkg.console.log`) is the place to start. See
[`docs/TASK-1.7-HANDOFF.md`](docs/TASK-1.7-HANDOFF.md) for the full state.

### Path A — run the CI job (no fast PC needed)

`.github/workflows/build-iso.yml` has a `build-kernel` job and a `build-iso`
job that refuses to build without the kernel `.deb`. It has **never been
executed** (it only triggers on a `v*` tag or manually). Trigger it:

```bash
gh workflow run build-iso.yml -f flavor=daily
gh run watch
```

If it succeeds, download `obsidian-kernel-deb` and `obsidian-daily-iso` from the
run and attach both to the tracking issue. If it fails, that failure log is
itself the contribution — open an issue with it. Do not lower the job's
requirements to make it pass.

### Path B — build locally

Requirements: a native Linux host or WSL2 (not WSL1), 8+ cores, **32 GB RAM
recommended**, ~60 GB free disk for the tree plus artifacts, and a Debian or
Ubuntu userland.

```bash
git clone https://github.com/happymode-25/obsidian-os.git
cd obsidian-os

# Persistent tree: survives a failed run and resumes instead of restarting.
sudo KERNEL_BUILD=/var/tmp/kernel-build KBUILD_JOBS="$(nproc)" \
  ./scripts/build-kernel.sh

ls -lh build/kernel-out/
# expect obsidian-linux-image-<ver>-obsidian-h_*.deb and headers/libc-dev debs
```

Useful env vars: `OUTDIR`, `KBUILD_JOBS`, `KERNEL_BUILD`, `CHECK_ONLY=1`
(config merge + hardening assertion only, ~2 minutes), `DEBSRC_MIRROR`.

Then build and test the image:

```bash
sudo ./build/build-iso.sh --flavor daily --suite trixie \
  --kernel-deb build/kernel-out/obsidian-linux-image-*.deb

# Linux/macOS host (QEMU):
bash tests/boottest.sh build/out/obsidian-daily-trixie-amd64.iso --flavor daily --timeout 600

# Windows host:
powershell -File tests/boottest-win.ps1 -Iso build\out\obsidian-daily-trixie-amd64.iso -Flavor daily
```

The gate is strict. It requires `OBSIDIAN-OS-MARKER v1`, `OBSIDIAN-OS-READY`,
the overlay/AppArmor/firstboot checks, and — once flipped — 
`OBSIDIAN-CHECK kernel-identity: obsidian-hardened`. It also fails if
`Welcome to Debian` or `Debian GNU/Linux` appears anywhere in the console. That
is intentional: a green gate must be impossible on stock Debian.

### What a PR that closes Task 1.7 must contain

1. The `.deb` build succeeding, with the tail of the packaging log pasted in the
   issue (not the whole log).
2. `uname -r` from inside the booted image showing a version containing
   `obsidian-h`.
3. The gate output (all required markers) and the ISO sha256.
4. `kernel-identity	OBSIDIAN-CHECK kernel-identity: obsidian-hardened` added as
   `required` to `tests/boot-markers.conf`, **in the same commit**, and the gate
   re-run green after the flip.
5. Any fix to `scripts/build-kernel.sh` needed to get there, in that commit.

A PR that flips the marker without the log is not reviewable and will be closed.

---

## Other work that is open

See the [issues](https://github.com/happymode-25/obsidian-os/issues). Labelled
`good first issue` means no kernel build is required.

---

## Ground rules

- **Evidence over assertions.** Every "done" needs a command, its output, or an
  artifact. `docs/GAP-REPORT.md` explains why this is a rule and not a preference.
- **Never weaken the gate to go green.** If the image is wrong, the test should
  fail. Changing `tests/boot-markers.conf`, `tests/boottest.sh` or
  `tests/boottest-win.ps1` to accept a weaker image will be rejected.
- **Keep the two runners in sync.** `boottest.sh` and `boottest-win.ps1` read the
  same `tests/boot-markers.conf`; if you add a marker, both must honour it.
- **Shell scripts are LF.** `.gitattributes` normalises on commit, but check
  `git diff --check` before pushing.
- **Do not commit build output, ISOs, keys, or logs.** `.gitignore` covers them.

## Setup

```bash
git clone https://github.com/happymode-25/obsidian-os.git
cd obsidian-os
python3 -m pip install --quiet pyyaml
python3 scripts/validate-build.py --self-test   # proves the validator can fail
python3 scripts/validate-build.py
```

Then read `docs/BUILD.md`, `docs/ARCHITECTURE.md`, and `docs/HARDENING.md`.

## Key files

| Path | What it is |
|---|---|
| `scripts/build-kernel.sh` | Hardened kernel build + `bindeb-pkg` packaging |
| `build/kernel/base-config-amd64.config` | Exact stock trixie amd64 config (the base) |
| `overlays/common/etc/obsidian/kernel/hardened.config` | The hardening fragment |
| `build/build-iso.sh` | ISO pipeline; `--kernel-deb` swaps out the stock kernel |
| `tests/boot-markers.conf` | The gate, single source of truth |
| `tests/boottest.sh` / `tests/boottest-win.ps1` | QEMU runners (Linux / Windows) |
| `overlays/common/usr/local/sbin/obsidian-boot-report` | Emits the attestation markers |

## Questions

Open an issue. If you are unsure whether something is in scope, ask before
writing a large patch — the fastest way to get a PR rejected here is to fix
something adjacent to the task while the task stays broken.
