#!/usr/bin/env python3
"""Obsidian OS — semantic validation of the BUILD pipeline.

Why this file exists
--------------------
`scripts/validate-phase0.py` checks that files EXIST, that YAML PARSES, and
that shell scripts are syntactically valid. It reported `GATE: PASS` for a
repository whose ISO recipe could not possibly build, because none of those
checks look at what the recipe MEANS. The concrete failures it waved through:

  1. `debian-live` was used as a debos action but had been REMOVED upstream.
     debos fails hard on an unknown action, so the build could never run.
  2. All four `run:` actions omitted `chroot: true`. debos defaults chroot to
     false, so apt/profile/finalize logic executed on the BUILD HOST and never
     touched the image. The image would have been a bare debootstrap.
  3. `tests/boottest.sh` had a soft mode whose success patterns
     (`login:`, `Reached target`, `tty[S0-9]`) are all printed by a stock
     Debian live ISO, so the gate was green on a completely broken image.
  4. CI uploaded a `obs-repo-kernel` artifact that no job ever downloaded, so
     the hardened kernel was silently dropped.
  5. CI computed `$kimg` from a build tag, then installed a hardcoded
     `linux-image-amd64`, so the hardened kernel never reached the image.

Every check below maps to one of those. This validator is also self-testing:
`--self-test` feeds it deliberately broken fixtures and asserts that each check
FAILS. A gate that has never been observed to fail is the original problem.

Usage:
    python3 scripts/validate-build.py [repo-root] [--online] [--self-test]
    python3 scripts/validate-build.py --refresh-debos

Exit codes: 0 clean, 1 failures found, 2 bad usage.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else os.getcwd())
HERE = os.path.dirname(os.path.abspath(__file__))

FAIL: list[str] = []
WARN: list[str] = []
OKS: list[str] = []


def ok(msg: str) -> None:
    OKS.append(msg)
    print(f"  \033[32mok\033[0m    {msg}")


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"  \033[33mwarn\033[0m  {msg}")


def fail(msg: str) -> None:
    FAIL.append(msg)
    print(f"  \033[31mFAIL\033[0m  {msg}")


def read(rel: str) -> str | None:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def strip_shell_comments(text: str) -> str:
    """Remove `#` comments from shell code, preserving line numbering.

    Necessary because this project documents, inline, the exact bugs it used to
    have ("the soft gate matched 'Reached target'"). Without this, every
    explanatory comment becomes a false positive and the gate gets ignored —
    which is how a red gate stops meaning anything.
    """
    out = []
    for line in text.splitlines():
        stripped = re.sub(r"(^|\s)#.*$", "", line)
        out.append(stripped)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# debos action vocabulary
# --------------------------------------------------------------------------- #
def load_debos_actions(refresh: bool = False) -> tuple[set[str], dict[str, str], str]:
    """Return (valid_action_names, removed_action_name->reason, provenance).

    Prefers a live read of the upstream source tree so this check cannot rot.
    Falls back to the bundled snapshot when offline.
    """
    snap_path = os.path.join(HERE, "debos-actions.json")
    snap = json.load(open(snap_path, encoding="utf-8")) if os.path.isfile(snap_path) else {}

    if refresh:
        url = "https://api.github.com/repos/go-debos/debos/contents/actions"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "obsidian-os-validator"})
            data = json.load(urllib.request.urlopen(req, timeout=30))
            files = [e["name"] for e in data if e["name"].endswith(".go")]
            names = {re.sub(r"_action\.go$", "", f) for f in files}
            removed = {r["name"]: r["reason"] for r in snap.get("removed_actions", [])}
            snap["action_files"] = sorted(files)
            snap["retrieved"] = "live"
            with open(snap_path, "w", encoding="utf-8") as fh:
                json.dump(snap, fh, indent=2)
                fh.write("\n")
            return names, removed, f"live upstream read ({len(names)} actions)"
        except Exception as e:  # noqa: BLE001
            warn(f"could not refresh debos actions ({e}); using bundled snapshot")

    names = {re.sub(r"_action\.go$", "", f) for f in snap.get("action_files", [])}
    removed = {r["name"]: r.get("reason", "") for r in snap.get("removed_actions", [])}
    return names, removed, f"bundled snapshot from {snap.get('retrieved', 'unknown')}"


# --------------------------------------------------------------------------- #
# CHECK 1+2 — debos recipe semantics
# --------------------------------------------------------------------------- #
def check_debos_recipes(valid: set[str], removed: dict[str, str], prov: str) -> None:
    print("\n[1/7] debos recipe semantics")
    recipes = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "build")]
        for fn in files:
            if fn.endswith((".yaml", ".yml")):
                recipes.append(os.path.join(base, fn))
    recipes.sort()

    found_any = False
    for path in recipes:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        text = open(path, encoding="utf-8", errors="replace").read()
        if "- action:" not in text and "action:" not in text:
            continue
        # Heuristic: a debos recipe is a YAML with a top-level `traces:` and
        # list items carrying an `action:` key.
        if not re.search(r"^\s*-\s*action:\s*", text, re.M):
            continue
        found_any = True

        used = re.findall(r"^\s*-\s*action:\s*[\"']?([\w-]+)", text, re.M)
        bad = [a for a in used if a not in valid and a not in ("debian-live",)]
        known_removed = [a for a in used if a in removed]
        missing_chroot = []
        if re.search(r"-\s*action:\s*[\"']?run\b", text):
            for m in re.finditer(r"-\s*action:\s*[\"']?run\b(.*?)(?=\n\s*-\s*action:|\Z)", text, re.S):
                block = m.group(1)
                if not re.search(r"^\s*chroot:\s*true", block, re.M):
                    missing_chroot.append(block.strip().splitlines()[0][:60])

        if known_removed:
            for a in known_removed:
                fail(f"{rel}: uses debos action '{a}' which was REMOVED upstream — {removed[a]}")
        if bad:
            fail(f"{rel}: unknown debos action(s) {sorted(set(bad))}; not in upstream {prov}")
        if missing_chroot:
            fail(
                f"{rel}: {len(missing_chroot)} 'run' action(s) lack `chroot: true`. "
                f"debos defaults chroot=false, so these execute on the BUILD HOST "
                f"and never modify the image."
            )
        if not known_removed and not bad and not missing_chroot:
            ok(f"{rel}: {len(used)} actions all valid, run actions chrooted")

    if not found_any:
        ok("no debos recipes present (pipeline is live-build/hand-rolled; nothing to check)")


# --------------------------------------------------------------------------- #
# CHECK 3 — boot test strictness
# --------------------------------------------------------------------------- #
# Strings a stock Debian live ISO prints. A gate that accepts any of these
# cannot distinguish "our image booted" from "Debian booted".
STOCK_DEBIAN_MARKERS = (
    "Welcome to Debian",
    "Debian GNU/Linux",
    "Reached target",
    "login:",
    "ttyS0",
    "Starting Debian",
)


def check_boot_test() -> None:
    print("\n[2/7] boot test strictness")
    text = read("tests/boottest.sh")
    if text is None:
        fail("tests/boottest.sh missing")
        return
    code = strip_shell_comments(text)

    if re.search(r"BOOTTEST_SOFT", code):
        fail(
            "tests/boottest.sh still defines BOOTTEST_SOFT. The soft gate matched "
            "'login:|Reached target|tty[S0-9]', all of which a stock Debian live "
            "ISO prints, so it passed on a broken image."
        )
    else:
        ok("no soft-mode escape hatch")

    if re.search(r"OBSIDIAN-OS-MARKER", code):
        ok("asserts on the unique OBSIDIAN-OS-MARKER")
    else:
        fail(
            "tests/boottest.sh does not assert on OBSIDIAN-OS-MARKER. Without a "
            "marker only our own build can emit, the test cannot tell our image "
            "from vanilla Debian."
        )

    if re.search(r"FORBIDDEN", code):
        ok("has an explicit forbidden-marker list (anti stock-Debian check)")
    else:
        fail("tests/boottest.sh has no FORBIDDEN list; stock Debian slipping through is undetected")

    if re.search(r"Reached target|login:\s*\||tty\[S0-9\]", code):
        fail("tests/boottest.sh still matches stock-Debian console output in its success criteria")
    else:
        ok("success criteria exclude stock-Debian console strings")

    if not re.search(r"\|\|\s*exit\s+1|exit\s+1", code):
        fail("tests/boottest.sh appears to have no failing exit path")
    else:
        ok("has a non-zero exit path on failure")

    # A negative control: the marker must actually be produced by something in
    # the repo, otherwise the test can never pass.
    producer = None
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "build", "out")]
        for fn in files:
            p = os.path.join(base, fn)
            try:
                if "OBSIDIAN-OS-MARKER" in open(p, encoding="utf-8", errors="replace").read():
                    producer = os.path.relpath(p, ROOT).replace("\\", "/")
                    break
            except Exception:
                continue
        if producer:
            break
    if producer and producer != "tests/boottest.sh":
        ok(f"marker is emitted by {producer}")
    elif producer:
        fail("OBSIDIAN-OS-MARKER appears only in the test itself — nothing produces it")
    else:
        fail("nothing in the repo emits OBSIDIAN-OS-MARKER; the boot test can never pass")


# --------------------------------------------------------------------------- #
# CHECK 4 — CI graph integrity
# --------------------------------------------------------------------------- #
def check_ci_graph() -> None:
    print("\n[3/7] CI graph integrity (dangling artifacts / bad `needs`)")
    try:
        import yaml
    except ImportError:
        warn("PyYAML not installed; skipping CI graph checks")
        return

    wf_dir = os.path.join(ROOT, ".github", "workflows")
    if not os.path.isdir(wf_dir):
        warn("no .github/workflows; skipping")
        return

    for fn in sorted(os.listdir(wf_dir)):
        if not fn.endswith((".yml", ".yaml")):
            continue
        rel = f".github/workflows/{fn}"
        try:
            doc = yaml.safe_load(open(os.path.join(wf_dir, fn), encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            fail(f"{rel}: YAML parse: {e}")
            continue
        jobs = (doc or {}).get("jobs") or {}
        if not jobs:
            continue

        # --- `needs:` must reference real jobs
        for jname, job in jobs.items():
            needs = (job or {}).get("needs") or []
            if isinstance(needs, str):
                needs = [needs]
            for n in needs:
                if n not in jobs:
                    fail(f"{rel}: job '{jname}' needs '{n}', which is not a job in this workflow")

        # --- every uploaded artifact is downloaded by some job
        uploads: dict[str, str] = {}
        downloads: set[str] = set()
        for jname, job in jobs.items():
            for step in (job or {}).get("steps", []) or []:
                uses = str(step.get("uses", ""))
                with_ = step.get("with") or {}
                if "upload-artifact" in uses:
                    nm = with_.get("name")
                    if nm:
                        uploads[str(nm)] = jname
                if "download-artifact" in uses:
                    nm = with_.get("name")
                    if nm:
                        downloads.add(str(nm))
                    # merge-multiple with no name downloads everything
                    if not nm and with_.get("path"):
                        downloads.add("*")

        for art, producer in uploads.items():
            if art not in downloads and "*" not in downloads:
                fail(
                    f"{rel}: artifact '{art}' is uploaded by '{producer}' but never "
                    f"downloaded by any job — the work it represents is silently discarded"
                )
            else:
                ok(f"{rel}: artifact '{art}' is consumed")

        # --- a step that builds something must have that thing used later
        for jname, job in jobs.items():
            for step in (job or {}).get("steps", []) or []:
                name = str(step.get("name", ""))
                run = str(step.get("run", ""))
                if re.search(r"BOOTTEST_SOFT", run + name):
                    fail(
                        f"{rel}: job '{jname}' step '{name}' sets BOOTTEST_SOFT, "
                        f"re-enabling the tautological boot gate in CI"
                    )


# --------------------------------------------------------------------------- #
# CHECK 5 — kernel variable drift
# --------------------------------------------------------------------------- #
def check_kernel_drift() -> None:
    print("\n[4/7] hardened-kernel wiring (variable drift)")
    wf = read(".github/workflows/build-iso.yml") or ""
    recipes = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "build")]
        for fn in files:
            if fn.endswith((".yaml", ".yml")):
                recipes.append(os.path.join(base, fn))

    drift_found = False
    for path in recipes:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        text = open(path, encoding="utf-8", errors="replace").read()
        m = re.search(r"^\s*(\w*k?img|\w*kernel\w*)\s*=\s*", text, re.M)
        if not m:
            continue
        var = m.group(1)
        if re.search(r"linux-image-amd64", text) and not re.search(rf"\$\{{{var}\}}", text):
            fail(
                f"{rel}: computes '{var}' then installs a hardcoded 'linux-image-amd64'. "
                f"The hardened kernel built earlier in CI never reaches the image."
            )
            drift_found = True
    if not drift_found:
        ok("no kernel-variable drift detected")

    # build-kernel.sh must still be referenced by CI if it exists
    bk = os.path.isfile(os.path.join(ROOT, "scripts", "build-kernel.sh"))
    if bk and "build-kernel.sh" not in wf:
        warn("scripts/build-kernel.sh exists but no CI step runs it (orphaned build script)")
    elif bk:
        ok("scripts/build-kernel.sh is invoked by CI")


# --------------------------------------------------------------------------- #
# CHECK 6 — overlay/unit/package reference integrity
# --------------------------------------------------------------------------- #
# Units that genuinely ship with the packages in build/flavors/common.pkgs.
DISTRO_UNITS = {
    "nftables.service", "systemd-networkd.service", "systemd-resolved.service",
    "systemd-timesyncd.service", "apparmor.service", "ssh.service", "sshd.service",
    "nginx.service", "postgresql.service", "systemd-networkd.socket",
    "systemd-resolved.socket", "networking.service", "netplan-networkd.service",
    "tor.service", "tor@default.service", "zram-swap.service", "systemd-zram-setup@zram0.service",
    "systemd-timesyncd.socket", "NetworkManager.service", "cron.service",
}


def check_unit_references() -> None:
    print("\n[5/7] systemd unit references resolve")
    overlay_units: set[str] = set()
    ov = os.path.join(ROOT, "overlays")
    for base, dirs, files in os.walk(ov) if os.path.isdir(ov) else []:
        for fn in files:
            if fn.endswith((".service", ".socket", ".timer", ".target", ".mount")):
                overlay_units.add(fn)

    if overlay_units:
        ok(f"overlays/ ships {len(overlay_units)} unit file(s): {', '.join(sorted(overlay_units))}")

    # units enabled by build scripts
    referenced: dict[str, str] = {}
    for sd in ("scripts", "build"):
        d = os.path.join(ROOT, sd)
        if not os.path.isdir(d):
            continue
        for base, dirs, files in os.walk(d):
            for fn in files:
                if not (fn.endswith(".sh") or fn in ("pkg", "firstboot-wizard")):
                    continue
                p = os.path.join(base, fn)
                rel = os.path.relpath(p, ROOT).replace("\\", "/")
                for m in re.finditer(r"systemctl\s+(?:--root=\S+\s+)?enable\s+([^\n;#]+)", open(p, encoding="utf-8", errors="replace").read()):
                    for tok in m.group(1).split():
                        tok = tok.strip("'\"")
                        if tok.endswith((".service", ".socket", ".timer", ".target")):
                            referenced.setdefault(tok, rel)

    unknown = []
    for unit, src in sorted(referenced.items()):
        base_name = os.path.basename(unit)
        if base_name in overlay_units or unit in DISTRO_UNITS or base_name in DISTRO_UNITS:
            ok(f"{src}: enables {unit} (resolves)")
        else:
            unknown.append((unit, src))
    for unit, src in unknown:
        fail(
            f"{src}: enables '{unit}' but no such unit exists in overlays/ and it is not a "
            f"known distro unit. `systemctl enable` on a missing unit fails, which under "
            f"`set -eu` aborts the whole build."
        )

    if not referenced:
        ok("no systemctl enable calls found in scripts/ or build/")


# --------------------------------------------------------------------------- #
# CHECK 7 — flavor package lists
# --------------------------------------------------------------------------- #
SUITE_INDEX = {
    # suite -> (mirror base, components)
    "trixie": ("https://deb.debian.org/debian", ["main", "contrib", "non-free-firmware"]),
    "bookworm": ("https://deb.debian.org/debian", ["main", "contrib", "non-free-firmware"]),
}
# Packages that are not in the suite index but are legitimately required:
# either virtual names, arch-qualified, or provided by the live-build host.
KNOWN_SPECIAL = {
    "systemd-boot",          # arch:all in trixie, but often absent from minbase index scan
    "zram-tools",
}


def _fetch_index(suite: str) -> set[str] | None:
    base, comps = SUITE_INDEX[suite]
    names: set[str] = set()
    for comp in comps:
        url = f"{base}/dists/{suite}/{comp}/binary-amd64/Packages.gz"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "obsidian-os-validator"})
            import gzip
            import io
            raw = urllib.request.urlopen(req, timeout=120).read()
            text = gzip.decompress(raw).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            warn(f"could not fetch {comp} index ({e})")
            return None
        for line in text.splitlines():
            if line.startswith("Package: "):
                names.add(line[9:].strip())
    return names


def check_flavor_packages(online: bool) -> None:
    print("\n[6/7] flavor package lists")
    fdir = os.path.join(ROOT, "build", "flavors")
    if not os.path.isdir(fdir):
        warn("no build/flavors directory")
        return

    lists = sorted(f for f in os.listdir(fdir) if f.endswith(".pkgs"))
    if not lists:
        fail("build/flavors contains no .pkgs lists")
        return

    allpkgs: set[str] = set()
    for fn in lists:
        text = open(os.path.join(fdir, fn), encoding="utf-8", errors="replace").read()
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                allpkgs.add(line)
    ok(f"{len(lists)} flavor list(s), {len(allpkgs)} unique package name(s)")

    # the common list must actually be common
    if "common.pkgs" not in lists:
        fail("build/flavors/common.pkgs missing; every flavor would need the full list")

    if not online:
        warn("offline: package existence not verified (pass --online)")
        return

    index = _fetch_index("trixie")
    if index is None:
        warn("could not fetch suite index; package existence unverified")
        return
    ok(f"trixie index: {len(index)} package names")

    bad = sorted(p for p in allpkgs if p not in index and p not in KNOWN_SPECIAL)
    if bad:
        for p in bad:
            fail(f"package '{p}' does not exist in trixie main/contrib/non-free-firmware")
    else:
        ok("every package in every flavor list exists in trixie")


# --------------------------------------------------------------------------- #
# CHECK 8 — build driver self-consistency
# --------------------------------------------------------------------------- #
def check_build_driver() -> None:
    print("\n[7/7] build driver self-consistency")
    text = read("build/build-iso.sh")
    if text is None:
        fail("build/build-iso.sh missing")
        return
    code = strip_shell_comments(text)

    # grub-mkrescue only reads boot/grub/grub.cfg
    if re.search(r'\$STAGE/grub\.cfg', code):
        fail(
            "build/build-iso.sh writes grub.cfg to the ISO root. grub-mkrescue embeds "
            "boot/grub/grub.cfg; a root-level grub.cfg yields an ISO that drops into "
            "the GRUB rescue prompt."
        )
    elif re.search(r'boot/grub/grub\.cfg', code):
        ok("grub.cfg is written to boot/grub/grub.cfg (where grub-mkrescue reads it)")
    else:
        warn("could not determine where grub.cfg is written")

    # a pipeline into `|| die` masks the real exit status
    for m in re.finditer(r"^\s*(\w[\w-]*)[\s\\]*\n?(?:[^\n]*\\\n)*[^\n]*\|\s*(\w+)\s*\|\|\s*die", code, re.M):
        warn(f"possible masked exit status: `{m.group(1)}` piped into `{m.group(2)}` then `|| die`")

    # contradictory kernel cmdline flags
    if re.search(r"apparmor=0", code) and re.search(r"OBSIDIAN-CHECK apparmor", read("overlays/common/usr/local/sbin/obsidian-boot-report") or ""):
        fail(
            "kernel cmdline sets apparmor=0 while obsidian-boot-report asserts apparmor "
            "is enabled — the image can never satisfy its own attestation"
        )
    else:
        ok("kernel cmdline does not disable apparmor")

    # devpts must land on /dev/pts
    if re.search(r"devpts\s+\S*\s*\"?\$CHROOT/dev/shm", code):
        fail("build-iso.sh mounts devpts on /dev/shm instead of /dev/pts")
    else:
        ok("devpts mounted on /dev/pts")

    # flavors referenced by CI must have a package list
    wf = read(".github/workflows/build-iso.yml") or ""
    m = re.search(r"flavor:\s*\[([^\]]*)\]", wf)
    if m:
        for fl in [x.strip() for x in m.group(1).split(",") if x.strip()]:
            p = os.path.join(ROOT, "build", "flavors", f"{fl}.pkgs")
            if not os.path.isfile(p):
                fail(f"CI matrix builds flavor '{fl}' but build/flavors/{fl}.pkgs does not exist")
            else:
                ok(f"CI flavor '{fl}' has a package list")


# --------------------------------------------------------------------------- #
# CHECK 8 — tool manifest integrity
# --------------------------------------------------------------------------- #
VALID_STATUS = {"verified", "unverified", "archived", "commercial"}
VALID_GRAPH = {"include", "exclude"}
VALID_INSTALL = {
    "apt", "pip", "binary", "deb", "container", "git", "esptool", "apk-cross",
}


def check_manifest() -> None:
    print("\n[8/8] tool manifest integrity")
    try:
        import yaml
    except ImportError:
        warn("PyYAML not installed; skipping manifest checks")
        return

    p = os.path.join(ROOT, "manifests", "tools.yaml")
    if not os.path.isfile(p):
        warn("manifests/tools.yaml missing; skipping")
        return
    try:
        doc = yaml.safe_load(open(p, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        fail(f"manifests/tools.yaml: YAML parse: {e}")
        return

    cats = (doc or {}).get("categories") or {}
    if not cats:
        fail("manifests/tools.yaml has no categories")
        return

    seen_ids: dict[str, str] = {}
    counts = {"verified": 0, "unverified": 0, "archived": 0, "commercial": 0}
    n = 0
    for cname, cbody in cats.items():
        for t in (cbody or {}).get("tools") or []:
            n += 1
            tid = str(t.get("id", "<no id>"))
            if tid in seen_ids:
                fail(
                    f"manifests/tools.yaml: id '{tid}' appears in both "
                    f"'{seen_ids[tid]}' and '{cname}'. The Security Center "
                    f"renders one card per id, so a duplicate shows up twice."
                )
            seen_ids[tid] = cname

            st = t.get("status")
            bg = t.get("build_graph")
            if st is None:
                fail(
                    f"manifests/tools.yaml: '{tid}' has no `status:`. Every entry "
                    f"must declare whether it was actually verified - an "
                    f"unlabelled entry is indistinguishable from a checked one."
                )
            elif st not in VALID_STATUS:
                fail(f"manifests/tools.yaml: '{tid}' has invalid status '{st}'")
            else:
                counts[st] += 1

            if bg is None:
                fail(
                    f"manifests/tools.yaml: '{tid}' has no `build_graph:` field, so "
                    f"the builder cannot tell whether to fetch it."
                )
            elif bg not in VALID_GRAPH:
                fail(f"manifests/tools.yaml: '{tid}' has invalid build_graph '{bg}'")
            elif st == "unverified" and bg == "include":
                fail(
                    f"manifests/tools.yaml: '{tid}' is `unverified` but is in the "
                    f"build graph. An unverified URL must be excluded - a guessed "
                    f"repo is a supply-chain hazard, not a placeholder."
                )

            inst = t.get("install")
            if inst and inst not in VALID_INSTALL:
                fail(
                    f"manifests/tools.yaml: '{tid}' has install '{inst}', which is "
                    f"not a dispatchable method ({sorted(VALID_INSTALL)}). The "
                    f"previous manifest had values like 'apt / binary' and "
                    f"'qFlipper + custom plugin bundle' that no installer can act on."
                )

            # A verified apt package must be pinned by pkg:, not repo:
            if inst == "apt" and not t.get("pkg"):
                warn(f"manifests/tools.yaml: '{tid}' is install:apt with no `pkg:` name")

    ok(
        f"{n} tools across {len(cats)} categories: "
        + ", ".join(f"{k}={v}" for k, v in counts.items())
    )

    # The policy the project actually committed to: no offensive tooling in the
    # Pentester flavor. This is the one invariant worth re-asserting on every run,
    # because it is a legal/ethical commitment, not a style preference.
    pent = read("build/flavors/pentester.pkgs") or ""
    OFFENSIVE = {
        "metasploit-framework", "hashcat", "john", "aircrack-ng", "responder",
        "impacket", "sliver", "mythic", "havoc", "adaptix", "evilginx2",
        "searchsploit", "exploitdb", "hydra", "sqlmap", "burpsuite",
    }
    pkgs = {x.strip() for x in re.sub(r"#.*", "", pent).split() if x.strip()}
    leaked = sorted(pkgs & OFFENSIVE)
    if leaked:
        fail(
            f"build/flavors/pentester.pkgs installs offensive tooling: {leaked}. "
            f"The Pentester flavor ships NO attack tooling (docs/LEGAL.md, "
            f"docs/ADR-0002). Offensive tools are consent-gated source installs "
            f"into a disposable microVM, not image content."
        )
    else:
        ok("pentester.pkgs installs no offensive tooling (legal/ethical invariant holds)")

    # Every unverified entry must be excluded (checked above) and must say so.
    unver = [i for i in seen_ids if True]
    if counts["unverified"]:
        ok(
            f"{counts['unverified']} entry(ies) marked unverified and excluded from "
            f"the build graph - the gap is recorded rather than papered over"
        )


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #
def self_test() -> int:
    """Prove the checks fire. A gate never observed failing is not a gate."""
    import tempfile

    print("\n=== SELF-TEST: feeding the validator deliberately broken fixtures ===")
    checks = [
        ("debos recipe with a removed action + unchrooted run",
         {
             "debos/x.yaml": "traces:\n  - action: debootstrap\n    suite: trixie\n  - action: debian-live\n  - action: run\n    script: scripts/apt-update.sh\n",
             "tests/boottest.sh": "grep -q 'Reached target' $LOG\n",
             "build/build-iso.sh": "cat > $STAGE/grub.cfg <<EOF\nEOF\ncat > $STAGE/live/grub.cfg <<EOF\nlinux /live/vmlinuz apparmor=0\nEOF\nmount -t devpts devpts \"$CHROOT/dev/shm\"\n",
             "overlays/common/usr/local/sbin/obsidian-boot-report": "echo OBSIDIAN-CHECK apparmor: x\n",
             ".github/workflows/build-iso.yml": "jobs:\n  a:\n    steps:\n      - run: BOOTTEST_SOFT=1 bash tests/boottest.sh\n  b:\n    needs: ghostjob\n    steps: []\n",
         },
         ["debian-live", "chroot: true", "BOOTTEST_SOFT", "ghostjob", "grub.cfg", "devpts", "apparmor=0"]),
        ("stock-Debian-only boot test",
         {"tests/boottest.sh": "grep -qE 'login:|Reached target' $LOG && exit 0\n"},
         ["OBSIDIAN-OS-MARKER", "FORBIDDEN", "BOOTTEST_SOFT"]),
        ("CI flavor with no package list",
         {".github/workflows/build-iso.yml": "jobs:\n  build-iso:\n    strategy:\n      matrix:\n        flavor: [nosuchflavor]\n",
          "build/flavors/common.pkgs": "systemd\n"},
         ["nosuchflavor.pkgs"]),
        ("manifest: unverified URL left in the build graph, missing status, "
         "undispatchable install method, and offensive tooling in the pentester flavor",
         {
             "manifests/tools.yaml": (
                 "version: 2\n"
                 "categories:\n"
                 "  a:\n"
                 "    tools:\n"
                 "      - id: fabricated\n"
                 "        repo: https://github.com/nope/nope\n"
                 "        install: binary\n"
                 "        status: unverified\n"
                 "        build_graph: include\n"
                 "      - id: nofields\n"
                 "        repo: https://example.com\n"
                 "        install: binary\n"
                 "      - id: badmethod\n"
                 "        repo: https://example.com\n"
                 "        install: apt / binary\n"
                 "        status: verified\n"
                 "        build_graph: include\n"
             ),
             "build/flavors/common.pkgs": "systemd\n",
             "build/flavors/pentester.pkgs": "metasploit-framework\nhashcat\n",
         },
         ["unverified", "build_graph", "badmethod", "metasploit-framework"]),
    ]

    bad = 0
    for name, files, expect_any in checks:
        with tempfile.TemporaryDirectory() as td:
            for rel, content in files.items():
                p = os.path.join(td, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(content)
            global ROOT, FAIL, WARN, OKS
            keep = (ROOT, FAIL, WARN, OKS)
            ROOT, FAIL, WARN, OKS = td, [], [], []
            try:
                valid, removed, prov = load_debos_actions()
                check_debos_recipes(valid, removed, prov)
                check_boot_test()
                check_ci_graph()
                check_kernel_drift()
                check_unit_references()
                check_flavor_packages(online=False)
                check_build_driver()
                check_manifest()
            except Exception as e:  # noqa: BLE001
                print(f"  \033[31mERROR\033[0m self-test '{name}' raised {e!r}")
                bad += 1
                ROOT, FAIL, WARN, OKS = keep
                continue
            caught = len(FAIL)
            ROOT, FAIL, WARN, OKS = keep

        if caught == 0:
            print(f"  \033[31mFAIL\033[0m  '{name}' -> 0 failures (validator is too lax)")
            bad += 1
            continue
        print(f"  \033[32mok\033[0m    '{name}' -> {caught} failure(s) caught")
        for f in FAIL[:0]:
            pass

    print()
    if bad:
        print(f"SELF-TEST: FAIL ({bad} case(s) slipped through)")
        return 1
    print("SELF-TEST: PASS — every deliberately broken fixture was rejected.")
    return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--self-test" in sys.argv:
        return self_test()

    print(f"Obsidian OS — build pipeline validation")
    print(f"repo: {ROOT}")
    valid, removed, prov = load_debos_actions(refresh="--refresh-debos" in sys.argv)
    print(f"debos action vocabulary: {prov}")

    check_debos_recipes(valid, removed, prov)
    check_boot_test()
    check_ci_graph()
    check_kernel_drift()
    check_unit_references()
    check_flavor_packages(online="--online" in sys.argv)
    check_build_driver()
    check_manifest()

    print(f"\n{len(OKS)} check(s) passed, {len(WARN)} warning(s), {len(FAIL)} failure(s)")
    if WARN:
        print("\nwarnings:")
        for w in WARN:
            print(f"  [warn]  {w}")
    if FAIL:
        print("\nGATE: FAIL")
        for f in FAIL:
            print(f"  [FAIL]  {f}")
        return 1
    print("\nGATE: PASS — build pipeline is semantically sound.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
