# ADR-0001 — Replace the debos build recipe with a shell pipeline, and drop the Arch second base

- **Status:** Accepted
- **Date:** 2026-09-27
- **Supersedes:** the build design in `docs/ARCHITECTURE.md` §3 and
  `docs/PLAN.md` 0.5 / 0.5b as previously written
- **Evidence:** `docs/GAP-REPORT.md` §1, §5, §6

---

## Context

Phase 0 delivered a build system built on **debos**, driven by two YAML recipes:
`debos/obsidian.yaml` (Debian trixie) and `debos/arch/obsidian-arch.yaml`
(Arch, a "rolling secondary base"). The intent was a declarative recipe that CI
would execute, so that the image contents were described as data rather than as
shell side effects.

That intent was sound. The implementation could not have worked.

### Finding 1 — `debian-live` is not a debos action

`debos/obsidian.yaml` specified `action: debian-live`. That action **was removed
from debos upstream.** Verified against `go-debos/debos`: there is no
`debian_live_action.go`, and the action is absent from the current debos README's
action table. debos fails hard on an unknown action name, so the recipe aborted
before doing any work.

The action is also the specific one that would have produced a *vanilla Debian
live ISO* — meaning that in the window where it still existed, the build could
have reported success while silently discarding every overlay and package the
recipe contained.

### Finding 2 — every `run` action executed on the wrong machine

All four `run:` actions omitted `chroot: true`. debos documents the default
plainly: *"If unset, chroot is set to false and the resulting script is executed
outside the chroot."* So the profile-application, finalize, and apt-update logic
all ran **on the CI runner**, against the runner's own filesystem, and never
touched the image. The artifact would have been an untouched `debootstrap` with
an Obsidian filename on it.

### Finding 3 — the Arch recipe had the identical bugs, plus a fabricated action

`debos/arch/obsidian-arch.yaml` had all four unchrooted `run` actions *and* used
`action: arch-bootstrap`, which is not a debos action at all. It was never a
partial implementation of anything.

### Finding 4 — there is no "Debian/Arch hybrid base"

The design assumed a base image that spans both distributions. No such artifact
exists. The two recipes would have had to be independent images, and
`pkg`'s documented "`apt` / `pacman` — one manifest, two backends" split
had no mechanism behind it: a package name valid in one distribution is not
valid in the other, so a single manifest cannot resolve against both without a
mapping layer that was never designed or written.

### Finding 5 — CI could not have caught any of this

The boot test's soft mode matched `login:`, `Reached target`, and `tty[S0-9]`.
A stock Debian live ISO prints all three. Combined with Finding 1 — where the
recipe could substitute a stock Debian image — the gate was structurally
incapable of failing on precisely the failure it existed to detect. A separate
`build-kernel` job uploaded `obs-repo-kernel` and no job consumed it, so the
hardened kernel was discarded while the ISO step installed a hardcoded
`linux-image-amd64` anyway.

## Decision

**1. Retire debos. The build is a plain shell pipeline: `build/build-iso.sh`.**

```
mmdebstrap/debootstrap  →  package set  →  overlays  →  update-initramfs
                       →  mksquashfs  →  grub-mkrescue
```

`debootstrap`/`mmdebstrap` → packages → overlays → `mksquashfs` →
`grub-mkrescue`, with the flavor package list passed to the bootstrap as
`--include` so the base system and flavor packages download in one parallel apt
transaction.

`mmdebstrap` is preferred over `debootstrap` and this is not a preference for
newness. `debootstrap` fetches each `.deb` with a single serial `wget` using
GNU wget's defaults of `--dns-timeout=900 --connect-timeout=900 --tries=20`. On
any host whose network path accepts a connection and then stalls, **one package
blocks the entire bootstrap for fifteen minutes.** Measured on the WSL1 build
host: `debootstrap` reached 10 of ~70 packages in 20 minutes and stalled
permanently; `mmdebstrap` completed the same bootstrap in 754 seconds. It is
also the tool Debian's own `live-build` now uses.

**2. Drop the Arch second base entirely.** One base, Debian trixie. `pkg`
becomes a single-backend resolver (`apt` + `flatpak`).

**3. Replace the boot test with one that can fail.** `tests/boottest.sh` now
requires a marker (`OBSIDIAN-OS-MARKER`) that only `obsidian-boot-report` can
emit, and explicitly *fails* on the fingerprints of a stock Debian live ISO.
No soft mode, no `BOOTTEST_SOFT` escape.

## Alternatives considered

**live-build (`lb_config`)** — Debian's official live-image tool. Rejected as
config-fiddly for a pipeline that will grow six flavors and per-flavor kernel
cmdlines; the customization surface is a 200-line config plus hook scripts, which
is the same shell we are already writing, with more indirection. Reconsidered if
we ever need live-build's `persistence` or `volatile` support.

**mkosi** — a better conceptual fit (systemd-native, declarative, better
reproducibility story) and the direction to take for 1.0. Deferred because
building a *custom* base rather than one from a package manifest is a different
design, and getting there while also fixing a broken CI pipeline compounds two
risks. Revisit at 1.0 with the reason written down: reproducibility.

**Fix the debos recipe instead of replacing it.** The two real bugs are
one-line fixes. Rejected because the third finding is structural: a YAML
recipe cannot be tested by a gate, and the bug that actually reached a green CI
run was not "the recipe has a typo" but "nothing verified that the recipe's
output was the recipe at all." A shell pipeline can be `bash -n`'d, executed,
and asserted on.

**Keep Arch, fix it later.** Rejected per Finding 4. There is no coherent
version of "fix it later" for a base image that cannot exist.

## Consequences

**Good**

- The build runs. It was impossible before.
- The artifact can be *verified* to be ours: the boot test can now fail.
- One base means one package-naming authority, one hardening story, one CI
  matrix. The `pacman` branch of `pkg` was specified but never implementable.
- `mmdebstrap`'s parallel download and explicit per-connection timeouts make
  the build tolerant of the flaky networks real CI runners sit behind.

**Bad / accepted costs**

- We gave up declarative-ness. The image contents are now described by shell,
  so `validate-build.py` has to parse shell to check it. That check exists and
  is one of the reasons the gate is trustworthy, but it is more fragile than
  validating YAML.
- We gave up debos's digest-pinned reproducibility. Builds track trixie, so two
  builds of one commit can differ. Deferred to `snapshot.debian.org` in Phase 2.
- The two YAML recipes were the most legible description of the image in the
  repo. Losing them costs documentation. Mitigated by `docs/BUILD.md`, which
  documents the pipeline step by step.

**Follow-up required by this ADR**

- `scripts/validate-build.py` reads debos' action vocabulary from upstream so
  that this class of bug cannot recur silently, and enforces `chroot: true`
  against any recipe that reappears. Neither is free — the vocabulary snapshot
  is a bundled JSON file (`scripts/debos-actions.json`) that can rot. It is
  refreshable over the network, and the validator prefers the live list.
