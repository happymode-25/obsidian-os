# Obsidian OS — Ghost (privacy-max / amnesic) overlay

Applied by `build/build-iso.sh` when `--flavor ghost`. This is what makes the
Ghost image genuinely different from the common overlay rather than a relabelled
copy.

| File | Effect |
|---|---|
| `etc/obsidian/ghost/amnesic` | presence marker; read by the boot report and the shutdown hook |
| `etc/obsidian/ghost/tor-mode` | marker that transparent Tor is the expected egress path |
| `etc/obsidian/ghost/cmdline.extra` | extra kernel cmdline, appended by the build driver |
| `etc/systemd/journald.conf.d/volatile.conf` | no logs on disk at all |
| `etc/obsidian/ghost/egress.nft` | Tor-only egress ruleset, loaded on demand |
| `usr/lib/systemd/system-shutdown/obsidian-memwipe.sh` | best-effort residue reduction |

## What "amnesic" can and cannot mean here

Being precise about this, because the previous revision of this file implied a
guarantee the platform cannot deliver:

- **Achievable.** No persistent writes. `Storage=volatile` keeps the journal in
  RAM only; the live session already runs from a squashfs with a tmpfs upper
  layer, so rebooting discards all state. zram swap is per-boot and its backing
  store never leaves RAM. `overlay=tmpfs` (see `cmdline.extra`) guarantees the
  squashfs itself is never written to.
- **Not achievable.** Wiping all RAM on shutdown. Modern kernels (5.10+ with
  `mem=type_isolate`, and lockdown) refuse `/dev/mem`, and
  `CONFIG_RANDOMIZE_BASE` plus KASLR means you cannot reliably overwrite your own
  physical address space from userspace. The honest position is that
  **amnesic mode protects against disk and swap forensics, not against a
  cold-boot RAM acquisition by an adversary with physical access.** If that
  threat is in scope, the answer is hardware: encrypted RAM (TME) or a
  disposable VM destroyed on power-off.
- `obsidian-memwipe.sh` therefore does only what is real: it shreds the zram
  device's backing state and drops key material it can actually reach. It does
  not pretend to `dd` over `/dev/mem`.

## Ordering note (the bug class this repo keeps hitting)

`egress.nft` is **not** loaded automatically. It is a default-deny ruleset, and
loading it before Tor is answering would black-hole the session. The intended
sequencing is: `tor.service` starts → `obsidian-tor-ready` verifies SOCKS →
`nft -f /etc/obsidian/ghost/egress.nft` → the common overlay's
`obsidian_kill` table becomes redundant and is flushed. Wiring that state
machine is tracked in docs/ROADMAP.md; until it exists, Ghost boots with the
common ruleset and the kill switch armed.
