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
import shutil
import subprocess
import sys
import tempfile
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

    # The markers moved to tests/boot-markers.conf so that boottest.sh and
    # boottest-win.ps1 cannot drift apart. The gate's substance is now in that
    # file, so the checks below have to look there - checking the runner's shell
    # source for the marker names would have passed on a runner that no longer
    # checks anything at all.
    markers_raw = read("tests/boot-markers.conf")
    if markers_raw is None:
        fail(
            "tests/boot-markers.conf missing. It holds the required/forbidden "
            "marker lists shared by boottest.sh and boottest-win.ps1; without it "
            "the two runners would each need their own copy and would drift."
        )
        return
    req = [l.split(None, 1)[1].strip() for l in markers_raw.splitlines()
           if l.strip() and not l.strip().startswith("#") and l.split(None, 1)[0] == "required"]
    forb = [l.split(None, 1)[1].strip() for l in markers_raw.splitlines()
            if l.strip() and not l.strip().startswith("#") and l.split(None, 1)[0] == "forbidden"]

    if not req:
        fail("tests/boot-markers.conf lists no `required` markers; every image would pass")
    elif not any("OBSIDIAN-OS-MARKER" in m for m in req):
        fail(
            "tests/boot-markers.conf requires no OBSIDIAN-OS-MARKER. Without a "
            "marker only our own build can emit, the test cannot tell our image "
            "from vanilla Debian."
        )
    else:
        ok(f"asserts on the unique OBSIDIAN-OS-MARKER ({len(req)} required marker(s))")

    if not forb:
        fail(
            "tests/boot-markers.conf lists no `forbidden` markers; stock Debian "
            "slipping through is undetected"
        )
    else:
        ok(f"has an explicit forbidden-marker list ({len(forb)} entries)")

    # Both runners must actually read the shared list, and both must refuse to
    # run with an empty one. A runner that silently treats "no markers" as
    # "nothing to check" is the soft gate all over again.
    for runner in ("tests/boottest.sh", "tests/boottest-win.ps1"):
        rtext = read(runner)
        if rtext is None:
            fail(f"{runner} missing")
            continue
        if "boot-markers.conf" not in rtext:
            fail(
                f"{runner} does not reference tests/boot-markers.conf. The two "
                f"boot-test runners must share one definition of the gate."
            )
        elif not re.search(r"refus\w*|cannot fail|no required markers", rtext, re.I):
            fail(
                f"{runner} reads the shared marker list but has no guard against "
                f"an empty one, so an emptied list would make it pass everything."
            )
        else:
            ok(f"{runner} uses the shared marker list and guards against an empty one")

    if re.search(r"Reached target|login:\s*\||tty\[S0-9\]", code):
        fail("tests/boottest.sh still matches stock-Debian console output in its success criteria")
    else:
        ok("success criteria exclude stock-Debian console strings")

    if not re.search(r"\|\|\s*exit\s+1|exit\s+1", code):
        fail("tests/boottest.sh appears to have no failing exit path")
    else:
        ok("has a non-zero exit path on failure")

    # A negative control: the marker must actually be PRODUCED by something that
    # runs at boot, otherwise the test can never pass.
    #
    # "Some file contains the string" is not good enough. Docs, the CI workflow
    # (in a comment), the validator itself and the marker list all mention
    # OBSIDIAN-OS-MARKER, and a naive first-match search reported the workflow
    # YAML as the thing that "emits" it - which is a file that cannot echo. So
    # look for an executable that actually echoes the marker, then check that
    # something references it, because a script nothing invokes also never runs.
    skip_dirs = {".git", "node_modules", "build", "out", "__pycache__", ".github", "docs", "scripts"}
    echo_re = re.compile(r"echo\b[^\n]*OBSIDIAN-OS-MARKER")
    producer = None
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in files:
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            if not (rel.startswith("overlays/") or rel.startswith("tests/")):
                continue
            try:
                body = open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            if rel.startswith("tests/") or not echo_re.search(body):
                continue  # the test asserting on it is not the thing producing it
            producer = rel
            break
        if producer:
            break

    if not producer:
        fail(
            "no executable in the repo echoes OBSIDIAN-OS-MARKER. The boot test "
            "requires it, so it can never pass — and worse, a gate that can "
            "never pass is a gate nobody trusts."
        )
        return

    # An emitter nothing calls is the same failure one level deeper: the string
    # is in the right place, but nothing runs it at boot.
    name = os.path.basename(producer)
    referenced = False
    for base, dirs, files in os.walk(os.path.join(ROOT, "overlays")):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for fn in files:
            try:
                if name in open(os.path.join(base, fn), encoding="utf-8", errors="replace").read():
                    referenced = True
                    break
            except Exception:
                continue
        if referenced:
            break
    if not referenced:
        fail(
            f"{producer} echoes OBSIDIAN-OS-MARKER but nothing in overlays/ "
            f"references it. The marker would never be printed, so the boot test "
            f"can never pass."
        )
    else:
        ok(f"marker is echoed by {producer}, and a unit or overlay invokes it")


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

    # ---- the WSL1 OFD-lock shim -------------------------------------------
    # On a host without F_OFD_SETLK the shim is the only reason systemd can be
    # configured, so its wiring is checked as carefully as the rest of the
    # pipeline. The failure it works around is a silent one: without the shim
    # the build dies deep inside dpkg with a message about /etc/passwd, which
    # points nowhere near the cause.
    if re.search(r"F_OFD_SETLK|ofd_locks_work", code):
        # the probe must exist: pattern-matching "WSL1" by hostname would send a
        # WSL2 host, which runs a real kernel, down the shim path
        if "ofd_locks_work" not in code:
            fail(
                "build-iso.sh references OFD locks but has no capability probe. "
                "Detecting WSL1 by hostname/version sends WSL2 — which runs a real "
                "kernel and needs no shim — down the shim path."
            )
        else:
            ok("OFD-lock handling is gated on a capability probe, not a host check")

        if "wsl1-ofd-lock-shim.c" not in text:
            fail("build-iso.sh mentions OFD locks but not the shim source it would need")
        elif read("build/wsl1-ofd-lock-shim.c") is None:
            fail("build/wsl1-ofd-lock-shim.c is missing; hosts without OFD locks cannot build")
        else:
            ok("build/wsl1-ofd-lock-shim.c present")

        # The shim must be removed from the image. Leaving it in would preload a
        # lock-stub into every process at first boot, including anything the user
        # installs afterwards.
        if re.search(r"cp\s+[^|;&]*shim[^|;&]*\$CHROOT", code) and not re.search(
            r"still present in the image", code
        ):
            fail(
                "build-iso.sh copies the OFD-lock shim into the chroot but never asserts "
                "it was removed. A shipped shim preloads a lock-stub into every process "
                "on first boot."
            )
        elif re.search(r"still present in the image", code):
            ok("OFD-lock shim removal from the image is asserted, not assumed")

        # LD_PRELOAD does not reach dpkg's maintainer scripts: dpkg sanitises
        # their environment. ld.so.preload is read by the loader itself.
        if re.search(r"LD_PRELOAD", code) and "ld.so.preload" not in code:
            fail(
                "build-iso.sh injects the shim via LD_PRELOAD. dpkg sanitises the "
                "environment of the maintainer scripts it spawns, so LD_PRELOAD never "
                "reaches systemd's postinst. Use /etc/ld.so.preload."
            )
        elif "ld.so.preload" in code:
            ok("shim is injected via ld.so.preload (survives dpkg's env sanitising)")

        # Every other check here is a text pattern. This one is not, because the
        # shim is C and a shim that exists but does not compile is invisible to
        # everything else: the build only compiles it on a host WITHOUT OFD
        # locks, so CI on an ordinary runner never reaches that code at all. A
        # shim that rotted into non-compiling source would therefore pass every
        # gate in this repository and still break every WSL1 build. So compile
        # it, and check the symbols survived linking.
        src = os.path.join(ROOT, "build", "wsl1-ofd-lock-shim.c")
        cc = shutil.which("gcc") or shutil.which("cc")
        if not os.path.isfile(src):
            pass  # already reported above
        elif cc is None:
            warn(
                "no C compiler on this host, so the OFD-lock shim was not compiled "
                "or symbol-checked; that part of the validation did not happen"
            )
        else:
            with tempfile.TemporaryDirectory() as td:
                so = os.path.join(td, "shim.so")
                try:
                    r = subprocess.run(
                        [cc, "-O2", "-fPIC", "-shared", "-o", so, src, "-ldl"],
                        capture_output=True, text=True, timeout=180,
                    )
                except subprocess.TimeoutExpired:
                    fail(f"compiling build/wsl1-ofd-lock-shim.c with {cc} timed out")
                    r = None
                if r is not None and r.returncode != 0:
                    diag = (r.stderr or r.stdout or "").strip().splitlines()
                    fail(
                        f"build/wsl1-ofd-lock-shim.c does not compile ({cc} exit "
                        f"{r.returncode}): {diag[0] if diag else 'no diagnostic'}"
                    )
                elif r is not None:
                    # Compiling is not enough. If the overrides are not exported
                    # there is no interposition at all, and the build fails later
                    # with the original /etc/passwd error while looking as though
                    # a shim had been installed.
                    nm = shutil.which("nm")
                    want = ("take_etc_passwd_lock", "take_etc_shadow_lock", "fcntl")
                    if not nm:
                        warn("no `nm` on this host; shim exports not verified")
                    else:
                        n = subprocess.run(
                            [nm, "-D", "--defined-only", so],
                            capture_output=True, text=True, timeout=60,
                        )
                        absent = [w for w in want if w not in n.stdout]
                        if absent:
                            fail(
                                "the compiled OFD-lock shim does not export "
                                f"{', '.join(absent)}. Without those symbols there is no "
                                "interposition, so the build would fail later with the "
                                "original /etc/passwd error while appearing to have a shim."
                            )
                        else:
                            ok(f"OFD-lock shim compiles and exports its overrides ({cc})")


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
# CHECK 9 — profile <-> flavor wiring
# --------------------------------------------------------------------------- #
# profiles/*.yaml and build/flavors/*.pkgs are two independent descriptions of
# the same user-facing choice. They drifted: the profiles had no field naming
# their build flavor at all, the names disagreed (profile `daily-driver` vs
# flavor `daily`, profile `privacy-max` vs flavor `ghost`), and seven list
# elements packed several packages into one string. Nothing detected any of it,
# because nothing checked.


def check_profile_flavor_wiring() -> None:
    print("\n[9/9] profile <-> flavor wiring")
    try:
        import yaml
    except ImportError:
        warn("PyYAML not installed; skipping profile checks")
        return

    flavor_dir = os.path.join(ROOT, "build", "flavors")
    if not os.path.isdir(flavor_dir):
        fail("build/flavors/ is missing; there are no flavors to map onto")
        return
    flavors = {
        f[: -len(".pkgs")]
        for f in os.listdir(flavor_dir)
        if f.endswith(".pkgs") and f != "common.pkgs"
    }
    if not flavors:
        fail("build/flavors/ contains no flavor package lists")
        return

    pdir = os.path.join(ROOT, "profiles")
    if not os.path.isdir(pdir):
        fail("profiles/ is missing; the first-boot wizard has nothing to offer")
        return

    mapped: dict[str, str] = {}
    for fn in sorted(os.listdir(pdir)):
        if not fn.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(pdir, fn)
        # \t is a literal tab, which YAML forbids for indentation. Reject it with
        # the line number rather than letting the parser emit a message that
        # points at the wrong place (it reported lines 13-14 for a tab on 12).
        raw = open(path, encoding="utf-8").read()
        for i, line in enumerate(raw.splitlines(), 1):
            if line.startswith("\t") or (line[: len(line) - len(line.lstrip())].count("\t")):
                fail(f"profiles/{fn}:{i}: leading tab. YAML forbids tabs for indentation.")
                break
        try:
            doc = yaml.safe_load(raw)
        except Exception as e:  # noqa: BLE001
            fail(f"profiles/{fn}: YAML parse: {e}")
            continue
        if not isinstance(doc, dict):
            fail(f"profiles/{fn}: top level is {type(doc).__name__}, not a mapping")
            continue

        name = doc.get("name")
        flavor = doc.get("flavor")

        if not name:
            fail(f"profiles/{fn}: no `name:` key")
            continue
        if not flavor:
            fail(
                f"profiles/{fn}: no `flavor:` key. Nothing machine-readable ties this "
                f"profile to a build flavor, so the picker can offer a choice the "
                f"build cannot produce. (Note the names differ on purpose: profile "
                f"`privacy-max` is flavor `ghost`, profile `daily-driver` is flavor "
                f"`daily`.)"
            )
            continue
        if flavor not in flavors:
            fail(
                f"profiles/{fn}: flavor '{flavor}' has no build/flavors/{flavor}.pkgs. "
                f"Known flavors: {sorted(flavors)}"
            )
            continue
        if flavor in mapped:
            fail(
                f"profiles/{fn} and profiles/{mapped[flavor]} both claim flavor "
                f"'{flavor}'; the wizard would offer the same image twice."
            )
            continue
        mapped[flavor] = fn

        # A list element holding several whitespace-separated names is the
        # signature of the bug: it only works for a consumer that word-splits,
        # and silently mis-installs for one that does not.
        for entry in doc.get("packages") or []:
            names = str(entry).split()
            if len(names) > 1:
                fail(
                    f"profiles/{fn}: package entry {entry!r} packs {len(names)} "
                    f"packages into one list element ({', '.join(names)}). One "
                    f"package per element, or the consumer guesses."
                )

        # Dead-init advert: runit/s6 came with the dropped multi-base design.
        if str(doc.get("init", "")).strip() not in ("", "systemd"):
            fail(
                f"profiles/{fn}: init={doc.get('init')!r}. ADR-0001 dropped the "
                f"multi-base design; there is no runit/s6 variant of this image, "
                f"so advertising one is a promise nothing can keep."
            )

    missing = sorted(flavors - set(mapped))
    if missing:
        fail(
            f"no profile offers build flavor(s) {missing}. A flavor the build can "
            f"produce but no wizard can select is either dead code or a missing "
            f"profile; decide which."
        )
    else:
        ok(f"all {len(flavors)} build flavors are offered by exactly one profile")

    # The Pentester flavor must not gain offensive tooling via a profile either.
    pent = None
    for fn, d in ((f, None) for f in os.listdir(pdir)):
        if fn.startswith("pentester") and fn.endswith((".yaml", ".yml")):
            pent = os.path.join(pdir, fn)
    if pent:
        doc = yaml.safe_load(open(pent, encoding="utf-8"))
        named = {n for e in (doc.get("packages") or []) for n in str(e).split()}
        bad = sorted(named & {"metasploit-framework", "hashcat", "john", "aircrack-ng"})
        if bad:
            fail(f"profiles/{os.path.basename(pent)} names offensive tooling: {bad}")
        else:
            ok("pentester profile names no offensive tooling")


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
         # boot-markers.conf and boottest-win.ps1 must be present or check 2
         # returns early on the missing shared list, and the fixture then "fails"
         # for a reason that has nothing to do with stock-Debian matching.
         {"tests/boottest.sh": "grep -qE 'login:|Reached target' $LOG && exit 0\n",
          "tests/boottest-win.ps1": "boot-markers.conf\n",
          # A `required` list made of a stock-Debian console string, and no
          # forbidden list at all. That is precisely the old soft gate: it
          # cannot tell our image from vanilla Debian.
          "tests/boot-markers.conf": "required\tReached target\nrequired\tlogin:\n"},
         ["OBSIDIAN-OS-MARKER", "forbidden", "BOOTTEST_SOFT", "Reached target"]),
        ("CI flavor with no package list",
         # build-iso.sh must be present: check_build_driver bails out on a
         # missing driver before it ever reaches the flavor lookup, so without
         # it this fixture was "caught" only by the unrelated missing-file
         # checks and the assertion below is what finally exposed that.
         {".github/workflows/build-iso.yml": "jobs:\n  build-iso:\n    strategy:\n      matrix:\n        flavor: [nosuchflavor]\n",
          "build/build-iso.sh": "cat > $STAGE/boot/grub/grub.cfg <<EOF\nlinux /live/vmlinuz quiet\nEOF\n",
          "build/flavors/common.pkgs": "systemd\n"},
         ["nosuchflavor"]),
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
        ("profile <-> flavor wiring: profile with no flavor, a flavor nothing "
         "offers, a packed package list, two profiles claiming one flavor, and a "
         "dead-init advert",
         {
             "build/flavors/common.pkgs": "systemd\n",
             "build/flavors/daily.pkgs": "live-boot\n",
             "build/flavors/orphan.pkgs": "live-boot\n",
             "profiles/nofavor.yaml": "name: no-flavor\npackages:\n  - live-boot\n",
             "profiles/wrongflavor.yaml": "name: wrong\nflavor: nosuchflavor\n",
             "profiles/packed.yaml": "name: packed\nflavor: daily\n"
                                     "packages:\n  - \"vim tmux curl\"\n",
             "profiles/dupA.yaml": "name: dup-a\nflavor: daily\n",
             "profiles/dupB.yaml": "name: dup-b\nflavor: daily\n",
             "profiles/deadinit.yaml": "name: dead-init\nflavor: orphan\ninit: runit\n",
             "profiles/pentester.yaml": "name: pentester\nflavor: daily\n"
                                        "packages:\n  - metasploit-framework\n",
             # A tab where YAML expects a space. The parse error it produces
             # points at the wrong line, so the check has to name the tab itself.
             "profiles/tabbed.yaml": "name: tabbed\nflavor: orphan\npackages:\n\t- live-boot\n",
         },
         ["no `flavor:`", "nosuchflavor", "packs", "both claim flavor", "runit",
          "no profile offers", "offensive", "leading tab"]),
        ("OFD shim copied into the image, with no assertion that it was removed",
         # The trigger token `ofd_locks_work` must be in real code, not a
         # comment: the check reads comment-stripped source, so a fixture that
         # only mentions it in a comment silently skips the whole block. That is
         # what made this fixture "pass" with no relevant failure at all.
         {
             "build/flavors/common.pkgs": "systemd\n",
             "build/wsl1-ofd-lock-shim.c": "int take_etc_passwd_lock(void){return 0;}\n",
             "build/build-iso.sh": (
                 "cat > $STAGE/boot/grub/grub.cfg <<EOF\nlinux /live/vmlinuz quiet\nEOF\n"
                 + "ofd_locks_work() { return 1; }\n"
                 + "cp $WORK/ofd/obsidian-ofd-shim.so $CHROOT/usr/lib/\n"
             ),
         },
         ["never asserts it was removed"]),
        ("OFD shim injected via LD_PRELOAD instead of ld.so.preload",
         {
             "build/flavors/common.pkgs": "systemd\n",
             "build/wsl1-ofd-lock-shim.c": "int take_etc_passwd_lock(void){return 0;}\n",
             "build/build-iso.sh": (
                 "cat > $STAGE/boot/grub/grub.cfg <<EOF\nlinux /live/vmlinuz quiet\nEOF\n"
                 + "ofd_locks_work() { return 1; }\n"
                 + "echo 'still present in the image'\n"
                 + "LD_PRELOAD=$WORK/ofd/obsidian-ofd-shim.so\n"
             ),
         },
         ["LD_PRELOAD", "ld.so.preload"]),
        ("OFD shim source exists but does not compile",
         {
             "build/flavors/common.pkgs": "systemd\n",
             "build/build-iso.sh": (
                 "cat > $STAGE/boot/grub/grub.cfg <<EOF\nlinux /live/vmlinuz quiet\nEOF\n"
                 + "ofd_locks_work() { return 1; }\n"
                 + "echo 'still present in the image' ld.so.preload\n"
             ),
             "build/wsl1-ofd-lock-shim.c": "this is not valid C at all ; ; ;\n",
         },
         ["does not compile"]),
        ("boot marker that nothing ever echoes, and an emitter nothing invokes",
         # Two ways to have the string in the tree without it ever reaching the
         # serial log: only documentation mentions it, and an overlay script
         # echoes it but no unit runs that script. Both make the gate
         # unpassable, and neither is visible to a "does the string appear
         # somewhere" check - the CI workflow alone satisfied that one.
         {
             "tests/boottest.sh": "grep -qF OBSIDIAN-OS-READY $LOG\n"
                                  "# see docs for OBSIDIAN-OS-MARKER\n",
             "tests/boottest-win.ps1": "boot-markers.conf\n",
             "tests/boot-markers.conf": "required\tOBSIDIAN-OS-MARKER v1\n"
                                        "required\tOBSIDIAN-OS-READY\n"
                                        "forbidden\tWelcome to Debian\n",
             "docs/NOTES.md": "the boot report should print OBSIDIAN-OS-MARKER\n",
             "overlays/common/usr/local/sbin/obsidian-boot-report":
                 "#!/bin/sh\necho \"OBSIDIAN-OS-MARKER v1\"\n",
         },
         ["echoes OBSIDIAN-OS-MARKER", "references it"]),
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
                check_profile_flavor_wiring()
            except Exception as e:  # noqa: BLE001
                print(f"  \033[31mERROR\033[0m self-test '{name}' raised {e!r}")
                bad += 1
                ROOT, FAIL, WARN, OKS = keep
                continue
            caught = len(FAIL)
            blob = " || ".join(FAIL)
            ROOT, FAIL, WARN, OKS = keep

        if caught == 0:
            print(f"  \033[31mFAIL\033[0m  '{name}' -> 0 failures (validator is too lax)")
            bad += 1
            continue

        # A non-zero failure count is not enough. Every check runs against every
        # fixture, so a fixture aimed at check 9 would "pass" if an unrelated
        # check happened to notice something else about it -- which is how a
        # gate can be dead code and still report green. Require the failures to
        # actually mention what this fixture broke.
        hit = [m for m in expect_any if m in blob]
        if not hit:
            print(
                f"  \033[31mFAIL\033[0m  '{name}' -> {caught} failure(s) caught, but "
                f"none mention any of {expect_any}.\n"
                f"         The check that should have caught this did not; something "
                f"else did."
            )
            bad += 1
            continue
        print(f"  \033[32mok\033[0m    '{name}' -> {caught} failure(s) caught, "
              f"citing {hit}")

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
    check_profile_flavor_wiring()

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
