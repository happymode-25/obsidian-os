#!/usr/bin/env python3
"""Verify every repo URL in manifests/tools.yaml.

Prints a table with the HTTP status of each URL so the manifest can be corrected
from evidence. Does not modify the manifest.
"""
import json
import re
import sys
import urllib.error
import urllib.request

PATH = "manifests/tools.yaml"
text = open(PATH, encoding="utf-8").read()

# Pull (id, name, url) triples in document order.
entries = []
for m in re.finditer(r"-\s*id:\s*(\S+)\s*\n(.*?)(?=\n\s*-\s*id:|\n\S|\Z)", text, re.S):
    tid = m.group(1).strip()
    block = m.group(2)
    nm = re.search(r"^\s*name:\s*(.+)$", block, re.M)
    rp = re.search(r"^\s*repo:\s*(.+)$", block, re.M)
    entries.append((tid, nm.group(1).strip() if nm else "?", rp.group(1).strip() if rp else ""))

print(f"found {len(entries)} entries\n")

UA = {"User-Agent": "obsidian-os-manifest-verify"}


def check(url):
    if "," in url:  # multiple repos in one field
        parts = [u.strip() for u in url.split(",") if u.strip()]
    else:
        parts = [url]
    out = []
    for u in parts:
        try:
            req = urllib.request.Request(u, headers=UA, method="GET")
            with urllib.request.urlopen(req, timeout=25) as r:
                out.append((u, r.status, ""))
        except urllib.error.HTTPError as e:
            note = ""
            if e.code in (403, 429):
                note = "rate-limited/blocks-bots (not necessarily dead)"
            out.append((u, e.code, note))
        except Exception as e:
            out.append((u, "ERR", type(e).__name__))
    return out


bad = []
for tid, name, url in entries:
    for u, status, note in check(url):
        mark = "ok  " if status == 200 else "BAD "
        if status != 200:
            bad.append((tid, name, u, status, note))
        shown = u.replace("https://", "")
        print(f"{mark} {tid:<16} {str(status):<5} {shown}  {note}")

print("\n" + "=" * 70)
print(f"DEAD OR UNVERIFIABLE: {len(bad)}")
for tid, name, u, status, note in bad:
    print(f"  {tid:<16} {str(status):<5} {name}")
    print(f"  {'':<16} {u}")
    if note:
        print(f"  {'':<16} note: {note}")

json.dump(
    [{"id": t, "name": n, "url": u, "status": s, "note": nt} for t, n, u, s, nt in bad],
    open("manifest-verify-failures.json", "w", encoding="utf-8"),
    indent=2,
)
print("\nwrote manifest-verify-failures.json")
