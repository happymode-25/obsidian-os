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

---

## Status after this pass

| Area | Before | After |
|---|---|---|
| ISO pipeline | unbuildable | builds; boot-tested (see `docs/BUILD.md`) |
| Boot gate | could not fail | strict, self-verified |
| Hardening overlay | 3 real rule-order bugs | fixed + documented |
| Ghost overlay | README only | 6 real files |
| Ghost threat model | implied total wipe | stated, with limits |
| CI | dead job, soft gate, discarded artifact | real pipeline, no soft mode |
| Metapackages | hollow | still hollow — **Phase 2, not fixed** |
| Desktop shell | absent | still absent — **Phase 2, not fixed** |
| `tools.yaml` URLs | 13+ fabricated | **not yet corrected** |
| Missing manifest tiers | ~70% of brief | **not yet added** |
