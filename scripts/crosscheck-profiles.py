#!/usr/bin/env python3
"""Cross-check docs/profiles/*.yaml against the build's flavor definitions.

These are two independent descriptions of the same thing: the flavor a user
picks, and the packages that flavor installs. If they drift, the profile picker
offers a choice the build cannot honour.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

# --- build flavors: the ground truth (build/flavors/<flavor>.pkgs) -----------
FLAVOR_DIR = os.path.join(ROOT, "build", "flavors")
flavors = set()
flavor_pkgs = {}
for fn in sorted(os.listdir(FLAVOR_DIR)):
    if not fn.endswith(".pkgs"):
        continue
    name = fn[: -len(".pkgs")]
    flavors.add(name)
    pkgs = set()
    for line in open(os.path.join(FLAVOR_DIR, fn), encoding="utf-8"):
        line = re.sub(r"#.*", "", line)
        for w in line.split():
            pkgs.add(w)
    flavor_pkgs[name] = pkgs

# --- profiles: the user-facing selector -------------------------------------
PROFILE_DIR = os.path.join(ROOT, "profiles")
profiles = {}
if os.path.isdir(PROFILE_DIR):
    for fn in sorted(os.listdir(PROFILE_DIR)):
        if not fn.endswith((".yaml", ".yml")):
            continue
        try:
            profiles[fn] = yaml.safe_load(
                open(os.path.join(PROFILE_DIR, fn), encoding="utf-8")
            )
        except Exception as e:
            print(f"  !! {fn}: YAML parse error: {e}")

print("=== build flavors (ground truth) ===")
for f in sorted(flavors):
    n = len(flavor_pkgs[f])
    tag = " (shared by all)" if f == "common" else ""
    print(f"  {f:<14} {n:>3} packages{tag}")

print(f"\n=== profiles ({len(profiles)} file(s)) ===")
for fn, doc in profiles.items():
    if not isinstance(doc, dict):
        print(f"  {fn}: top level is {type(doc).__name__}, not a mapping")
        continue
    # find the id field the build driver would key on
    pid = doc.get("id") or doc.get("name") or doc.get("flavor")
    print(f"  {fn:<28} id={pid!r}  keys={sorted(doc)[:8]}")

print("\n=== cross-checks ===")
problems = 0

# 1. every profile id must correspond to a real build flavor
for fn, doc in profiles.items():
    if not isinstance(doc, dict):
        continue
    pid = doc.get("id") or doc.get("flavor")
    if pid is None:
        print(f"  WARN {fn}: no `id:`/`flavor:` key, so nothing maps it to a build flavor")
        problems += 1
    elif pid not in flavors:
        print(f"  FAIL {fn}: id '{pid}' has no build/flavors/{pid}.pkgs")
        print(f"       the profile picker would offer a flavor the build cannot produce")
        problems += 1

# 2. reverse: every build flavor should be selectable
for f in sorted(flavors - {"common"}):
    if not any(
        isinstance(d, dict) and (d.get("id") or d.get("flavor")) == f
        for d in profiles.values()
    ):
        print(f"  WARN build flavor '{f}' is not offered by any profile")

# 3. profiles that name packages must be packages that exist in the flavor
for fn, doc in profiles.items():
    if not isinstance(doc, dict):
        continue
    pid = doc.get("id") or doc.get("flavor")
    declared = set()
    for key in ("packages", "install", "apt"):
        v = doc.get(key)
        if isinstance(v, list):
            declared |= {str(x) for x in v}
    if not declared:
        continue
    allowed = flavor_pkgs.get(pid, set()) | flavor_pkgs.get("common", set())
    extra = declared - allowed
    if extra:
        print(f"  WARN {fn}: declares packages not in the {pid} flavor list: {sorted(extra)}")
        print(f"       (only a warning: profiles may be aspirational, but they are not")
        print(f"        what the ISO contains)")

print(f"\n{problems} problem(s)")
