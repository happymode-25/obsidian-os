#!/usr/bin/env python3
"""Obsidian OS — Phase 0 static validation gate (docs/PLAN.md).

Checks that every Phase 0 deliverable exists, that YAML parses
(Go-template-aware for debos recipes), that shell scripts pass bash -n,
and that manifests/profiles are internally consistent.

Windows/WSL note: bash checks require WSL (`wsl` + `wslpath`); if the host
cannot provide them the gate warns and relies on CI, which runs the same
script on Linux.

Usage:  python3 scripts/validate-phase0.py [repo-root]
CI:     runnable as-is; abort the pipeline on exit 1.
"""
import os
import re
import shutil
import subprocess
import sys

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import yaml

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
FAIL = []
WARN = []


def note(msg):
    print("  " + msg)


# ---------------------------------------------------------------------- 1
print("[1/4] Required deliverables (PLAN.md Phase 0)")
REQUIRED = [
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/PLAN.md",
    "docs/BUILD.md",
    "docs/GAP-REPORT.md",
    "docs/ADR-0001-debos-replacement.md",
    "docs/COMPONENT-SOURCES.md",
    "docs/UNIFIED-SHELL.md",
    "docs/APPS.md",
    "docs/HARDENING.md",
    "docs/ROADMAP.md",
    "docs/LEGAL.md",
    # --- build pipeline (replaced the unbuildable debos recipe) ------------
    "build/build-iso.sh",
    "build/flavors/common.pkgs",
    "build/flavors/daily.pkgs",
    "build/flavors/ghost.pkgs",
    "build/flavors/server.pkgs",
    "build/flavors/developer.pkgs",
    "build/flavors/pentester.pkgs",
    "scripts/validate-build.py",
    "scripts/debos-actions.json",
    # --- overlays (moved out of debos/overlays-src) -------------------------
    "overlays/common/etc/sysctl.d/99-obsidian-hardened.conf",
    "overlays/common/etc/nftables.conf",
    "overlays/common/etc/apparmor.d/obsidianwm",
    "overlays/common/usr/local/sbin/obsidian-killswitch.sh",
    "overlays/common/usr/local/sbin/obsidian-boot-report",
    "overlays/common/etc/systemd/system/obsidian-boot-report.service",
    "overlays/common/etc/obsidian/kernel/hardened.config",
    "overlays/ghost/etc/obsidian/ghost/amnesic",
    "overlays/ghost/etc/obsidian/ghost/cmdline.extra",
    "overlays/ghost/etc/obsidian/ghost/egress.nft",
    "overlays/ghost/etc/systemd/journald.conf.d/volatile.conf",
    "overlays/ghost/usr/lib/systemd/system-shutdown/obsidian-memwipe.sh",
    # --- in-image scripts (called by scripts/firstboot-wizard) -------------
    "scripts/apply-profile.sh",
    "scripts/finalize.sh",
    "scripts/firstboot-wizard",
    "scripts/pkg",
    "scripts/usb-maker",
    "scripts/restorectl",
    "scripts/scaffold-packages.py",
    "scripts/boot-keys.sh",
    "scripts/build-kernel.sh",
    "profiles/daily-driver.yaml",
    "profiles/developer.yaml",
    "profiles/pentester.yaml",
    "profiles/server.yaml",
    "profiles/privacy-max.yaml",
    "manifests/tools.yaml",
    "shell/Microsoft.PowerShell_profile.ps1",
    "shell/bashrc.d/obsidian-aliases.sh",
    "apps/security-center/README.md",
    "apps/security-center/daemon/src/main.rs",
    "apps/ai-assistant/README.md",
    "debos/packages/obsidian-core/debian/control",
    "debos/packages/obsidian-core/debian/rules",
    "debos/packages/obsidianwm/debian/control",
    "debos/installer/settings.conf",
    "debos/installer/modules/partition.conf",
    "debos/installer/modules/bootloader.conf",
    "debos/installer/modules/users.conf",
    "tests/boottest.sh",
    ".github/workflows/build-iso.yml",
    "tools/enable-wsl2.ps1",
    "LICENSE",
]
# Files that used to be required and were deliberately removed. If any of these
# come back, the deletion was reverted by accident and the gate should say so.
RETIRED = {
    "debos/obsidian.yaml": "unbuildable (debian-live action removed upstream; run actions unchrooted)",
    "debos/arch/obsidian-arch.yaml": "same bug class, plus a second base contradicts the one-base decision",
    "scripts/make-overlays.sh": "build-time only; replaced by build/build-iso.sh",
    "scripts/apt-update.sh": "build-time only; build-iso.sh runs apt inside the chroot directly",
    "scripts/enable-services.sh": "enabled a dozen units that did not exist; build-iso.sh enables only what it installs",
    "scripts/arch-install.sh": "only called by the deleted Arch recipe",
    "debos/overlays-src": "moved to overlays/ at the repo root",
    "debos/components.lock": "placeholder guarding the deleted debos recipe",
}
missing = [f for f in REQUIRED if not os.path.exists(os.path.join(ROOT, f))]
if missing:
    FAIL.append("missing deliverables: " + ", ".join(missing))
else:
    note(f"all {len(REQUIRED)} deliverables present")

resurrected = [f for f in RETIRED if os.path.exists(os.path.join(ROOT, f))]
if resurrected:
    FAIL.append(
        "retired files are present again: " + ", ".join(sorted(resurrected))
        + " — see the RETIRED table in this script for why they were removed"
    )
else:
    note(f"all {len(RETIRED)} retired files stay retired")

# ---------------------------------------------------------------------- 2
print("[2/4] YAML parse")
TEMPLATE_LINE = re.compile(r"^\s*\{\{-")  # Go-template statement lines (debos)
yaml_files = []
for base, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
    yaml_files += [
        os.path.join(base, f)
        for f in files
        if f.endswith((".yaml", ".yml"))
        or ("installer" in base.replace("\\", "/") and f.endswith(".conf"))
    ]

for path in sorted(yaml_files):
    rel = os.path.relpath(path, ROOT)
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    content = "".join(l for l in lines if not TEMPLATE_LINE.match(l))
    # Mask inline Go-template expressions (debos recipes): {{ $x }} etc.
    content = re.sub(r"\{\{.*?\}\}", "TEMPLATE", content, flags=re.S)
    try:
        list(yaml.safe_load_all(content))
        note(f"{rel}: OK")
    except yaml.YAMLError as e:
        FAIL.append(f"{rel}: YAML error: {e}")

# ---------------------------------------------------------------------- 3
print("[3/4] shell syntax (bash -n)")


def bash_check(path):
    """Return (status, message): 'OK' | 'FAIL' | 'WARN'."""
    rel = os.path.relpath(path, ROOT)
    if os.name != "nt":
        try:
            r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        except Exception as e:  # noqa: BLE001
            return "WARN", f"{rel}: cannot run bash locally ({e}) — checked in CI"
        if r.returncode == 0:
            return "OK", rel
        return "FAIL", f"{rel}: bash -n: {r.stderr.strip()}"
    # Windows: route through WSL.
    if not shutil.which("wsl"):
        return "WARN", f"{rel}: WSL not available — checked in CI"
    try:
        wl = subprocess.run(["wsl", "wslpath", "-a", "-u", path],
                            capture_output=True, text=True)
        if wl.returncode != 0:
            return "WARN", f"{rel}: WSL wslpath unavailable — checked in CI"
        linux = wl.stdout.strip()
        r = subprocess.run(["wsl", "bash", "-n", linux],
                           capture_output=True, text=True)
    except Exception as e:  # noqa: BLE001
        return "WARN", f"{rel}: WSL bash check error ({e}) — checked in CI"
    if r.returncode == 0:
        return "OK", rel
    return "FAIL", f"{rel}: bash -n: {r.stderr.strip()}"


sh_scripts = []
for base, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
    for fn in files:
        if fn.endswith(".sh") or fn in (
            "pkg", "firstboot-wizard", "finalize", "usb-maker", "restorectl",
        ):
            sh_scripts.append(os.path.join(base, fn))
seen = set()
for path in sorted(sh_scripts):
    key = os.path.relpath(path, ROOT).replace("\\", "/")
    if key in seen:
        continue
    seen.add(key)
    status, msg = bash_check(path)
    if status == "OK":
        note(f"{msg}: OK")
    elif status == "WARN":
        WARN.append(msg)
    else:
        FAIL.append(msg)

# ---------------------------------------------------------------------- 4
print("[4/4] cross-checks")
with open(os.path.join(ROOT, "manifests", "tools.yaml"), encoding="utf-8") as fh:
    tools = yaml.safe_load(fh)
n = sum(len(cat["tools"]) for cat in tools["categories"].values())
print(f"  tools.yaml: {n} tools in {len(tools['categories'])} categories")
if n < 45:
    FAIL.append(f"tools.yaml only lists {n} tools (brief expects ~50)")

for pf in ("daily-driver", "developer", "pentester", "server", "privacy-max"):
    p = os.path.join(ROOT, "profiles", pf + ".yaml")
    with open(p, encoding="utf-8") as fh:
        d = yaml.safe_load(fh)
    print(f"  profile {pf}: posture={d.get('posture')} session={d.get('session')}")

print()
for w in WARN:
    print("  (warn) " + w)
if FAIL:
    print("GATE: FAIL")
    for f in FAIL:
        print("  [FAIL] " + f)
    sys.exit(1)
print("GATE: PASS — Phase 0 static validation green.")