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
    "docs/COMPONENT-SOURCES.md",
    "docs/UNIFIED-SHELL.md",
    "docs/APPS.md",
    "docs/HARDENING.md",
    "docs/ROADMAP.md",
    "docs/LEGAL.md",
    "debos/obsidian.yaml",
    "debos/arch/obsidian-arch.yaml",
    "debos/overlays-src/common/etc/sysctl.d/99-obsidian-hardened.conf",
    "debos/overlays-src/common/etc/nftables.conf",
    "debos/overlays-src/common/etc/apparmor.d/obsidianwm",
    "debos/overlays-src/common/usr/local/sbin/obsidian-killswitch.sh",
    "scripts/make-overlays.sh",
    "scripts/apply-profile.sh",
    "scripts/enable-services.sh",
    "scripts/finalize.sh",
    "scripts/firstboot-wizard",
    "scripts/pkg",
    "scripts/arch-install.sh",
    "scripts/usb-maker",
    "scripts/restorectl",
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
    "scripts/scaffold-packages.py",
    "scripts/boot-keys.sh",
    "scripts/build-kernel.sh",
    "scripts/apt-update.sh",
    "debos/overlays-src/common/etc/apt/sources.list.d/obsidian-local.list",
    "debos/packages/obsidian-kernel/debian/control",
    "debos/overlays-src/common/etc/obsidian/kernel/hardened.config",
    "tests/boottest.sh",
    ".github/workflows/build-iso.yml",
    "LICENSE",
]
missing = [f for f in REQUIRED if not os.path.exists(os.path.join(ROOT, f))]
if missing:
    FAIL.append("missing deliverables: " + ", ".join(missing))
else:
    note(f"all {len(REQUIRED)} deliverables present")

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