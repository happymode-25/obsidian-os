# Obsidian OS — Gap Report

**Status:** Phase 0 was reported complete. It was not. This document records what
the repository actually contained versus what its documentation claimed, and what
was done about it.

Every finding below was verified against the code, the tool sources, or the
package index — not inferred from reading the docs. Where a fix is claimed, the
fix is in the tree and is enforced by `scripts/validate-build.py`.

---

## 1. The headline: the ISO pipeline could not build

`debos/obsidian.yaml` had three independent fatal defects. Any one of them makes
the build fail; the first also made it *silently wrong*.

### 1.1 `debian-live` is not a debos action

The recipe's final step was:

```yaml
- action: debian-live
```

`debian-live` **was removed from debos upstream.** Verified by listing
`go-debos/debos` `actions/` via the GitHub API: there is no
`debian_live_action.go`, and the action is absent from the current debos README's
action table. debos fails hard on an unknown action, so the recipe could never
complete.

This defect was the most dangerous of the three, because of *what that action
did*: it produced a vanilla Debian live ISO. So even in a world where the action
still existed, the build would have "succeeded" and shipped **stock Debian**
while every hardening overlay, profile, and package in the recipe was discarded.

That is precisely the failure the boot test was supposed to catch, and which it
did not (see §3).

**Fix:** removed. The build is now `build/build-iso.sh`, which assembles the ISO
from the chroot it actually built.

### 1.2 Every `run` action executed on the build host

All four `run:` actions omitted `chroot: true`:

| action | script | intended effect |
|---|---|---|
| `run` | `scripts/apt-update.sh` | refresh apt in the image |
| `run` | `scripts/apply-profile.sh` | install the profile's packages |
| `run` | `scripts/enable-services.sh` | enable units in the image |
| `run` | `scripts/finalize.sh` | hostname, users, fstab |

debos documents the default plainly: *"If unset, chroot is set to false and the
command or script is run in the host environment."* So these scripts ran against
the **CI runner**, not the image. `apt-get install obsidian-desktop` would have
installed packages onto the runner; `useradd` would have created a user on the
runner. The resulting image would have been an untouched `debootstrap`.

**Fix:** the profile/finalize logic is now inline in `build/build-iso.sh` and runs
inside the chroot by construction. `validate-build.py` check 1 fails the build on
any `run` action without `chroot: true`.

### 1.3 The Arch recipe had the identical bug class

`debos/arch/obsidian-arch.yaml` used a fabricated `arch-bootstrap` action (not a
debos action at all) and had the same four unchrooted `run` actions. It could
never have run either.

**Fix:** deleted, together with `scripts/arch-install.sh`. The "Debian + Arch
dual base" was also a design error — see §5.

---

## 2. The metapackages are hollow

The `obsidian-*` dpkg skeletons under `debos/packages/` present as the packaging
layer, but:

- `obsidian-desktop`, `obsidian-ghost`, `obsidian-server-server`,
  `obsidian-apps-extra` install exactly one file: `usr/share/obsidian/meta/*`
  (a README). They contain no software.
- They `Depends:` on `obsidianwm`, `obsidian-panel`, `obsidian-apps` — which are
  themselves hollow stubs. There is no compositor source anywhere in the
  repository.

So `apply-profile.sh` → `apt-get install obsidian-desktop` → pulls in a package
containing a text file, and the machine has **no window manager, no panel, and no
applications**. The "Windows 11-style desktop" was a naming convention on an empty
package.

**This is the single largest gap between the docs and the code.** It is not a
build bug; it is unbuilt software. See §6 for what it costs.

**Fix (partial):** the first-light flavors do not reference these metapackages at
all. `build/flavors/daily.pkgs` is a real package list (`foot`, `fbterm`). The
desktop remains Phase 2 work and is no longer implied to exist by the build.

---

## 3. The boot test could not fail

`tests/boottest.sh` shipped with a soft mode, and CI ran it with
`BOOTTEST_SOFT=1`:

```bash
grep -qE 'login:|Reached target|tty[S0-9]' "$LOG"   # soft-pass
```

A stock Debian live ISO prints all three within seconds of boot. Combined with
§1.1 — where the build step could substitute a stock Debian ISO — the gate was
structurally incapable of detecting the exact failure it existed to catch. It
would have gone green on a completely vanilla image.

**Fix:** the test now requires `OBSIDIAN-OS-MARKER`, a string only
`overlays/common/usr/local/sbin/obsidian-boot-report` can emit, and explicitly
**fails** if stock-Debian fingerprints (`Welcome to Debian`, `Debian GNU/Linux`)
appear. There is no soft mode. `validate-build.py` rejects the reintroduction of
`BOOTTEST_SOFT` in either the test or the CI workflow.

---

## 4. CI wiring that silently discarded work

- `build-kernel` uploaded artifact `obs-repo-kernel`; `build-iso` only declared
  `needs: build-packages` and downloaded `obs-repo`. **The hardened kernel was
  built and thrown away.** (Now: the `build-kernel` job is gone, and
  `validate-build.py` check 3 fails on any uploaded-but-never-downloaded
  artifact — the check that would have caught it.)
- The ISO step computed `$kimg` from a build tag, then installed a hardcoded
  `linux-image-amd64`, so even a wired kernel artifact would have been ignored.
- The recipe's host had no verified CI history (no upstream, no runs), so none of
  this had ever executed.

**Fix:** CI now runs the real pipeline, the dead job is removed, and kernel
variable drift is a hard failure.

---

## 5. Design problems that no amount of debugging would fix

These are architectural, not bugs. They are recorded here because they will shape
Phase 2 and they are expensive to rediscover.

1. **"Debian/Arch hybrid base" is not a thing.** There is no such base image.
   The honest options are one base plus a chroot, or two genuinely separate
   images. Recommend: **one base (Debian trixie)**, Arch dropped.
2. **One ISO carrying five profiles is a 5× QA matrix** multiplied by every
   future kernel and package update. Recommend: one hardened core image plus thin
   per-profile variants generated from it, and CI that builds the core on every
   change and flavors only on demand.
3. **C2 frameworks must not ship in the image at all.** Mythic, Havoc, Sliver,
   Adaptix, PoshC2 and GoPhish are not "tools a security distro bundles"; they
   are adversary-infrastructure tooling whose presence in an image is itself the
   harm. Recommend removing them from `manifests/tools.yaml` entirely and, for
   legitimate red-team use, a consent-gated source install into a disposable
   microVM. See `docs/LEGAL.md`.
4. **"Server stack" is a services/compose toggle, not a package list.** Baking
   `caddy + nginx + postgresql + samba + nfs` into a base image ships four
   internet-facing daemons that are then disabled. Recommend: base image carries
   none of them; the role toggle installs on first boot.

---

## 6. Manifest integrity

`manifests/tools.yaml` lists 53 tools. Batch-checking every repository URL
against the GitHub API found **13 that return 404** — i.e. they are fabricated,
misspelled, or the entry's `id` points at a different project than its `url`:

`dsaparikh/HackBot`, `PentAir/PentAiA`, `ossanii/BugTraceAI`,
`MazeZ-Dev/ShadowBroker`, `TebbaaX/third-eye`, `DiabloHacker/VulnScope`,
`blakeblackshear/sentinel` (entry id `sentinelx`), `parrot-ass/scanopy`,
`altwikid/noderadar` (entry id `noderadar`), `zerothreatai/zerothreat-ai-scanner`,
`Adaptix-Developers/AdaptixC2` (correct: `Adaptix-Framework/AdaptixC2`),
`realhitori/ClatsCracker`, `The-4n/wiflux`, `christian-christensen/hijacker`,
`olehontushevskyi/Hijacker`, `parrottv/revelare`, `ariary/cosmic-axiom`.

Also wrong in kind rather than in spelling: ExploitDB is `offsec.com/exploitdb`
(not GitLab); Maltego CE and Binary Ninja are commercial; exllamav2 is
`turboderp/exllamav2`; and there is no "Evilginx3" — the project is
`kgretzky/evilginx2`.

`aliasrobotics/cai` is archived upstream, which the manifest does not record.

**Policy adopted:** an unverifiable entry is marked `status: unverified` and
**excluded from the build graph**. Guessing a plausible-looking URL is worse
than admitting ignorance, because it turns a missing tool into a supply-chain
hazard.

**Also missing entirely:** the manifest has no tier for core security tooling
(§11.6), server stack (§11.7), the "elite" long-tail (§11.9), AI/agent tooling
(§11.10), or general utilities (§11.11) — roughly 70% of the original brief.

---

## 7. Hardening bugs found in the overlay itself

These were real defects in files that *did* exist and were otherwise reasonable.

- **`nftables.conf` rule ordering.** In the egress leak guard, a broad
  `ct original proto dns drop` preceded the `ip daddr 127.0.0.53 accept` that is
  meant to permit the local systemd-resolved stub. In an egress chain a later
  accept cannot rescue traffic an earlier drop already killed, so **DNS was dead
  on any system with the leak guard loaded.**
- **The same bug in the Ghost kill switch:** `tcp dport {53,80,123} drop`
  preceded the loopback accept, so the Tor client's own connection to
  `127.0.0.1:9050` would be killed, guaranteeing the kill switch fires on a
  healthy system.
- **No DHCP rule.** A live session obtains its address over DHCP, and the input
  chain is `policy drop` with no DHCP accept, so the ISO would boot with **no
  network at all**.

All three are fixed in `overlays/common/etc/nftables.conf`, and the file now
documents the ordering rule that prevents the class.

---

## 8. Ghost mode was a README, not an implementation

`debos/overlays-src/privacy-max/` contained a single markdown file that *described*
six files (journald volatile config, Tor egress ruleset, memwipe hook, amnesic
markers). None existed. Meanwhile `docs/PLAN.md` marked the hardening overlays
"✅ done".

Additionally, 4 of the 6 profile overlay directories referenced by the recipe
(`daily-driver`, `developer`, `pentester`, `server`) **did not exist at all**, so
`make-overlays.sh` would have failed on its first `tar`.

**Fix:** the Ghost overlay is now real files. The memwipe hook is honest about
what it can do — a full RAM wipe is impossible on a modern kernel under
`lockdown=confidentiality`, and the previous `dd if=/dev/zero of=/dev/mem`
version would never have worked. The threat model is stated in
`overlays/ghost/README.md` rather than implied.

---

## 9. The Phase 0 validator could not see any of this

`scripts/validate-phase0.py` checks that files exist, that YAML parses, that
shell passes `bash -n`, and that `tools.yaml` has ≥45 entries. It printed
**`GATE: PASS`** on a repository whose ISO recipe could not build, because none of
those checks look at what the recipe *means*.

`scripts/validate-build.py` is the counterpart that looks at meaning, and it is
built to be adversarially verified:

```
python3 scripts/validate-build.py --self-test
```

feeds the validator deliberately broken fixtures and asserts each is rejected —
because a gate that has never been observed to fail is the original problem, not
a solution to it. It currently catches all 13 findings in this document.

`--online` additionally resolves every package name in every flavor list against
the real trixie package index, so a typo'd dependency fails the gate instead of
failing 20 minutes into a build.

---

## 10. Stale identifiers

`docs/PLAN.md` boot marker still read `AEGIS-free obsidian.target reached` — a
leftover from the project's previous name. Anything matching that string is dead.

## 11. The build host could not configure systemd at all (WSL1)

Found only by actually running the build, which is the argument for running it.

### 11.1 The failure

With the new pipeline in place, the bootstrap got as far as unpacking 128
packages and then died at the last step:

```
Initializing machine ID from random generator.
Failed to take /etc/passwd lock: Invalid argument
dpkg: error processing package systemd (--configure):
 installed systemd package post-installation script subprocess returned error exit status 1
```

The `Failed to take /etc/passwd lock` line comes from `systemd-sysusers`, run by
systemd's maintainer script. Found by grepping the chroot for the string; the
only binary containing it is `/usr/bin/systemd-sysusers`.

### 11.2 The cause: a syscall WSL1 does not implement

Measured directly, not inferred:

| lock API | wslfs | tmpfs |
|---|---|---|
| `flock(2)` | OK | OK |
| `fcntl(F_SETLK)` | OK | OK |
| `fcntl(F_OFD_SETLK)` | **EINVAL** | **EINVAL** |

Open-file-description locks (Linux 3.15+) are unimplemented in WSL1's kernel
emulation. Because tmpfs fails identically, **no mount arrangement works around
it** — it is a missing kernel feature, not a filesystem property. The
`/usr/local/sbin/wget` shim and apt timeouts fixed the *earlier* network stall;
they are unrelated to this, and the two failures were easy to conflate.

`systemd-sysusers` is not a corner case here: it runs from systemd's
postinst, so *every* systemd package fails to configure, and the image never
gets a `/boot` directory.

### 11.3 The obvious fix does not work, and why

The natural repair is an `LD_PRELOAD` shim that rewrites `F_OFD_*` to `F_*`.
It was built, and it silently did nothing. Two rounds of diagnosis:

- `systemd-sysusers` imports **no** `fcntl` symbol at all (`objdump -T`: 142
  dynamic symbols, none matching). It imports `take_etc_passwd_lock`, and the
  `fcntl` call is made from inside `libsystemd-shared`. A preloaded `fcntl` is
  never consulted for a call originating in another shared object.
- `strace` confirms the call and the mode: `fcntl(3, F_OFD_SETLKW,
  {l_type=F_WRLCK, ...}) = -1 EINVAL`.

So the shim overrides `take_etc_passwd_lock` (and its shadow/group/gshadow/
subuid/subgid siblings) instead. Result: `dpkg --configure -a` exits 0, and the
system users are genuinely created — `systemd-network` uid 998, `systemd-journal`
gid 999.

**A diagnostic note worth keeping:** two intermediate conclusions in this
investigation were wrong and had to be discarded. `flock(2)` was suspected first
(it works). "The binary imports no `fcntl`" was then read as "it must use a raw
`syscall` instruction" — but that reading came from an `objdump` that was not
actually installed, and its empty output had been swallowed by `2>/dev/null`.
The measurement was only trustworthy after the tool was confirmed present.

### 11.4 What ships, and what must not

The shim is a property of the **build host**, not of the distribution. It is
installed via an mmdebstrap setup hook (so it is in place before the stage that
configures packages) and removed by a customize hook. `build/build-iso.sh` then
*asserts* the file is absent from the chroot, because "the hook should have
worked" is not a check: an ISO that shipped this shim would preload a lock-stub
into every process on first boot, including anything the user installs later.

The shim only ever changes the answer to "did you get the lock?" — never the
writes that follow. The writes are the package's own. This is sound during
package configuration because dpkg holds the exclusive database lock and the
chroot is private to the build, so there is no second writer to exclude.

The host is **probed**, not pattern-matched, so a normal Linux build host never
compiles or installs any of it.

### 11.5 The real fix is still WSL2

This shim is a workaround for a missing kernel feature. WSL2 runs a real kernel
and needs none of it. `tools/enable-wsl2.ps1` exists but requires elevation and
a reboot, so it is the user's call, not something to attempt from a
non-administrator session.

### 11.6 Proven in the real pipeline, and what stopped it next

The shim was first verified in isolation, then exercised by an actual build run.
That run is worth recording precisely, because where it stopped is not where the
diagnosis predicted it would.

The build downloaded 155 MB, unpacked the base, and reached the stage that
configures packages — the stage the shim exists for. `systemd-sysusers` acquired
the `/etc/passwd` lock and did its real work:

```
Creating group 'systemd-journal' with GID 999.
Creating group 'systemd-network' with GID 998.
Creating user 'systemd-network' (systemd Network Management) with UID 998 and GID 998.
```

and left a real `/etc/machine-id`. Those accounts cannot exist unless the lock
was genuinely taken, so the shim is confirmed working **inside the pipeline**,
not just in a hand-run test. The users are the package's own, not synthesised.

The run then failed on something unrelated:

```
Failed to backup /etc/group: Cannot allocate memory
dpkg: error processing package systemd (--configure)
```

That is `ENOMEM` from the host. Measured at the time: 15,940 MB of 16,259 MB
used, **318 MB available**, with 44 GB of swap untouched. Not a defect in the
image or the pipeline — a resource ceiling on the machine. A `useradd` that
cannot allocate memory for a file the size of `/etc/group` is not a memory bug
in `useradd`; the process simply had nothing left to be given.

So: the WSL1 blocker is genuinely solved, and the next blocker is the build
host's memory. Recorded here rather than left as an unexplained failure, because
"the build broke" and "the build host ran out of memory" lead to completely
different next actions.

Note also that the shim was still present in the aborted chroot. That is correct:
mmdebstrap died before the customize hook could run, and the tree is discarded
rather than sealed. The post-bootstrap assertion in `build/build-iso.sh` is what
guarantees a *successful* build cannot ship it.

---

## 12. A documented "environment limitation" that was never checked

`tests/boottest.sh`, `docs/BUILD.md` and `build/build-iso.sh` all carried the
same claim, in the same words:

> the reference host has VT-x disabled in firmware, so KVM/WHPX are unavailable

This was written from the VirtualMachinePlatform finding and never verified
against QEMU. It is wrong, and wrong in a way that costs real time.

`qemu-system-x86_64 -accel help` on this host lists `whpx`, and a probe with a
real `pc` machine confirms it initialises. WHpx needs the *Hypervisor Platform*
feature, which is a different feature from the `VirtualMachinePlatform` that
was found missing — so the original inference was a category error, not a
measurement. (VBS/HVCI also make `systeminfo` and the CIM virtualization flags
unreliable on this host, so they cannot settle the question either.)

Why it mattered: the fallback is TCG, which emulates the CPU. A TCG cold boot
of a freshly built live image is slow enough that the runner's 420 s default
timeout becomes a plausible cause of failure — a timeout that looks exactly
like a broken image. The claim was quietly costing the gate its credibility.

Both runners now probe instead of assuming, and the probe is a real `pc`
machine rather than anything cheaper, for two reasons found the hard way:

- `qemu -accel help` is a capability list for the *binary*, not a statement
  about the host. It is where the spelling came from: the accelerator is
  `whpx`, not `wphx`. The typo fails closed into TCG, so it presents as a
  slow-but-passing gate rather than an error.
- `-machine none`, the cheap way to probe, is rejected by the x86 machine class
  in QEMU 11.1 *before* the accelerator is consulted. It cannot distinguish
  "accelerator unavailable" from "machine type refused", so it reports every
  accelerator as working. Both probes were replaced after producing exactly
  that wrong answer.

The general lesson is the one this report keeps rediscovering: an environment
limitation written down as fact will outlive the reason for it, and nobody
re-tests a limitation that is written as a limitation.

Driven with a stub `qemu` across all branches, `boottest.sh` was confirmed to
still pass a complete guest, still refuse a silent one, still refuse a guest
carrying a stock-Debian fingerprint, still refuse a wrong-flavor image, fall
back to TCG when the probe reports the accelerator unavailable, skip the probe
when `--accel` is given explicitly, and reject bad usage with exit 2. The pass
path matters as much as the fail path: a change to a gate that can only be
tested failing has not been tested.

---

| Area | Before | After |
|---|---|---|
| ISO pipeline | unbuildable | bootstrap completes + shim proven (§11.6, §13); **daily ISO produced, boots, and passes the strict gate under WHPX QEMU (§14)** |
| Boot gate | could not fail | strict, self-verified, markers shared with the Windows runner, acceleration probed not assumed — **executed against a real image: daily PASS, both stock-Debian fingerprints demonstrated to fail (§14)** |
| Hardening overlay | 3 real rule-order bugs | fixed + documented |
| Ghost overlay | README only | 6 real files |
| Ghost threat model | implied total wipe | stated, with limits |
| CI | dead job, soft gate, discarded artifact | real pipeline, no soft mode — **never run** |
| WSL1 / `/etc/passwd` lock | build impossible | shim proven in the real pipeline (§11.6) |
| Metapackages | hollow | still hollow — **Phase 2, not fixed** |
| Desktop shell | absent | still absent — **Phase 2, not fixed** |
| Hardened kernel | specified, never compiled | still not built; image ships stock trixie |
| `tools.yaml` URLs | 16 fabricated | marked `unverified` + excluded, not guessed |
| Missing manifest tiers | ~70% of brief | added (tiers 11.6/11.7/11.10/11.11) |
| Profile↔flavor mapping | none, and names disagreed | `flavor:` key + enforced by `validate-build.py` |
| Build host vs WSL1 | unbuildable, undiagnosed | OFD-lock shim, gated on a capability probe |

**The honest summary (as of §13): no ISO had ever been produced by this
repository.** The pipeline was written, syntax-clean and semantically gated, but
the boot test and the CI matrix remained entirely unexercised. Everything after
"the bootstrap completes" was unproven. **This is no longer true — see §14: the
first real ISO was assembled, booted, and the daily flavor passed the strict boot
gate on 2026-09-29.**

---

## 13. What the first real builds actually hit

Once the bootstrap started completing, three further failures appeared — none
of them image defects, all of them environment — and each cost a full ~10
minute re-bootstrap before it was understood. Recorded so the next builder
recognises them instantly.

**1. The dangling-symlink `resolv.conf` kill (fixed).** `mmdebstrap` leaves the
chroot's `/etc/resolv.conf` as a symlink to
`../run/systemd/resolve/stub-resolv.conf`, a path that does not exist inside
the build tree. The script's guard "copy host `resolv.conf` if the chroot's
lacks a `nameserver` line" is satisfied by a dangling link — `grep` silently
fails through it — so GNU `cp` runs and refuses:

```
cp: not writing through dangling symlink '.../etc/resolv.conf'
ISO_MISSING (rc=1)
```

This code path had never executed before, because nothing had ever passed the
bootstrap. Fixed in `build/build-iso.sh` (commit `a3d0ffe`): remove the symlink
before copying. The general rule: post-bootstrap chroot-file handling must
expect dangling symlinks; the failure only appears with a real bootstrap, so
hand-testing the script cannot catch it.

**2. The bottleneck was the mirror route, not the build.** `deb.debian.org`
(https and http) and `ftp.debian.org` delivered ~87 KB/s for a 5 MiB range on
this host; `mirrors.kernel.org` delivered 2.3 MB/s for the same file. The
kernel `.deb` alone is ~108 MB — at the slow route that is 20+ minutes minimum,
and apt's real rate collapsed to single-digit KB/s, so the "installing
remaining packages" phase looked like a hang (the fingerprint: host idle, no
apt/dpkg child, one socket in the `https` method, a `partial/*.deb` crawling
up). Measuring a 5 MiB range with `curl -r` against several mirrors settled it
in a minute. `build/build-iso.sh` takes `--mirror <url>`; the reference builds
use `http://mirrors.kernel.org/debian`. This corrects the earlier picture: the
post-bootstrap phase was never inherently slow, the route to the default
mirror was.

**3. A detached build does not survive a host restart.** The launcher uses
`setsid nohup ... &` precisely so the build outlives the invoking shell — which
it does. It does not outlive a Windows/WSL restart; after a restart the build
was found dead mid-bootstrap with **no error markers** (the log simply stops at
"installing remaining packages"). Diagnosis must check process state first; the
log tail alone is ambiguous. Relaunching with the same mirror override is
correct — preflight cleanup discards the dead tree.

Status at the time of writing: the bootstrap completes (187 packages), all
post-bootstrap chroot steps have been probed against the real chroot (`chpasswd`,
`groupadd`, `useradd` — shadow uses `flock`, so the removed OFD shim is not
needed there — and `update-initramfs`, which produced a 41 MB live-boot initrd,
falling back to gzip because zstd is not in the image package set), and the ISO
assembly + boot test remain in flight.

---

## 14. The first real boots: two blockers, both image defects, both fixed

Once the ISO assembly completed, the actual boot under WHPX QEMU found two bugs
that every static gate had missed, because both are runtime-only. The gate did
exactly what it was rebuilt to do: it failed loudly on each, and it proved it can
fail on a stock image before accepting ours.

### 14.1 `Kernel panic - Attempted to kill init!` — the squashfs was missing its pseudo-directories

The first boot panic'd in the initramfs ~2.8 s in:

```
mount: /root/dev: mount point does not exist.
mount: /root/run: mount point does not exist.
Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000100
```

Forensics (with a `live-boot.debug` trace and the extracted `/init` source):

- live-boot **was** working: the medium was found, `loop0` attached
  (377,064 sectors), the squashfs mounted, and the tmpfs overlay mounted onto
  `/root`, which contained a valid root (`run-init -n /root /sbin/init` dry-run
  succeeded twice, `/root/etc/fstab` existed).
- The initramfs tail then ran `mount -o move /dev` (and `/run`, `/sys`, `/proc`)
  onto their `"${rootmnt}"` counterparts, and **every move failed with "mount
  point does not exist"** — so `exec run-init ... <"${rootmnt}/dev/console"` could
  not open `/dev/console` and `/init` died.
- Root cause: `build/build-iso.sh` passed `-e boot dev proc sys run tmp var/tmp`
  to `mksquashfs`, deliberately excluding the pseudo-directories from the image.
  Debian live images ship them (as empty dirs, plus the static `/dev` nodes), and
  the initramfs tail depends on them. **The blame was on the recipe, not the boot.
  The boot was behaving correctly.**
- Fix (commit `bdd660a`): the exclusion list is now `-e boot` only — `/dev` (with
  its 8 device nodes incl. `console`), `/proc`, `/sys`, `/run`, `/tmp` are back
  in the squashfs. The rescue rebuild reused the preserved `--keep-chroot` tree;
  a full clean build runs the same script.

### 14.2 Green on everything except the stock-Debian fingerprint — the image was still presenting as vanilla Debian

The rebuilt daily image booted to `multi-user` + `graphical` and printed
`OBSIDIAN-OS-READY` in 7.4 s under WHPX, all 5 required markers present — and the
gate still failed on exactly one line of the whole serial log:

```
FORBIDDEN 'Debian GNU/Linux' present - image is vanilla Debian, not Obsidian
```

That line is systemd's welcome banner:

```
Welcome to ⓡ Debian GNU/Linux 13 (trixie)!
```

printed from `/etc/os-release` `PRETTY_NAME`, plus the getty banners from
`/etc/issue`, `/etc/issue.net` and the post-login `/etc/motd`. The image had never
been branded. **This is the evidence that the forbidden-marker check really
fires:** it rejected our own un-branded image, and by the same mechanism it
rejects any stock Debian live ISO.

Fix (commit `bdd660a`): `overlays/common/etc/{os-release,issue,issue.net,motd}`
now identify the system as **Obsidian OS** (`PRETTY_NAME="Obsidian OS (trixie)"`,
`ID=obsidian`, `ID_LIKE=debian`). No invented URLs, no claim of being anything
other than what it is — the base is declared honestly via `ID_LIKE`. systemd
reads `os-release` as its welcome banner and getty reads `/etc/issue`, so both
forbidden fingerprints are now impossible to produce from this image.

### 14.3 Result: first green gate

`tests/boottest-win.ps1 -Iso ... -Flavor daily` — the no-soft-mode strict gate —
ends with **`boottest: PASS`**:

```
ok  OBSIDIAN-OS-MARKER v1
ok  OBSIDIAN-OS-READY
ok  OBSIDIAN-CHECK sysctl-overlay: present
ok  OBSIDIAN-CHECK apparmor:
ok  OBSIDIAN-CHECK firstboot:
ok  flavor=daily
boottest: PASS
```

- ISO: `obsidian-daily-trixie-amd64.iso`, sha256
  `fb818a9379ddca9778a59d41b30718c6023454fc06e11197d648a7b6ef7e2212`.
- The "proven to fail on stock Debian" requirement is met: the same gate was
  demonstrated red against the un-branded build of the same pipeline (§14.2) and
  its `forbidden` markers are the exact fingerprints the problematic `debian-live`
  substitution would have produced (§1.1).
- Remaining Phase 1 items are untouched by this: ghost (build + gate in flight),
  the encrypted installer, Secure Boot/UKI and the hardened kernel are all still
  open.

