# Obsidian OS — Unified Shell Specification

## 1. Design goal

> One prompt, three worlds. A user coming from **Windows**, **macOS**, or **Linux**
> runs their muscle-memory commands and they *work* — because a translation layer
> maps them onto the Linux core. PowerShell 7 is the default interactive shell
> (it *is* a real language, ships on Linux, and reads Windows habits); bash/zsh
> remain first-class, and a `pwrsh`/`bash` bridge lets you switch mid-thought.

```
┌─────────────────────────────── unified shell ───────────────────────────────┐
│  pwsh7 (default: Windows habits)      bash/zsh (Linux habits)               │
│  Microsoft.PowerShell_profile.ps1     .bashrc.d/obsidian-aliases.sh         │
│        │  dir copy type ipconfig           │  Get-Process sc dir            │
│        └──────────────┬────────────────────┘                                │
│                       ▼                                                     │
│              translation shims (pwsh functions / bash functions)            │
│                       ▼                                                     │
│              native Linux core: ls, cp, ss, systemctl, sudo …               │
└──────────────────────────────────────────────────────────────────────────────┘
```

Guidelines:
1. **No command is deleted** — natives stay native.
2. **Every Windows name maps to something real** (`dir` → `Get-ChildItem -Force`,
   `netstat` → `ss`). Output is reformatted to *feel* like the original where it
   matters (tasklist columns, ipconfig summary).
3. **Every GUI tool has a CLI** (`files` = Explorer, `settingsctl` = Settings,
   `securityctl`, `firewallctl`, `vmctl`, `nasctl`, `agentctl`, `serverctl`,
   `pkg` — and vice versa: `pkg -g` opens the App Store at the search query).
4. **macOS gestures map too** (`open` → `xdg-open`, `pbcopy/pbpaste`, `say`,
   `brew` → `pkg`, `defaults` → `dconf`).

## 2. Core translation tables

### 2.1 Files & directory (cmd → Linux)
| Windows | PowerShell (profile) | Linux native | Notes |
|---|---|---|---|
| `dir` | `Get-ChildItem -Force` | `ls -la` | hidden shown |
| `copy x y` | `Copy-Item` | `cp -v` | |
| `move x y` | `Move-Item` | `mv -v` | |
| `del/erase x` | `Remove-Item` | `rm -v` | |
| `type x` | `Get-Content` | `cat` | |
| `ren a b` | `Rename-Item` | `mv` | |
| `md/mkdir` | `New-Item -ItemType Directory` | `mkdir -p` | |
| `rd` | `Remove-Item -Recurse` | `rm -r` | |
| `tree` | `tree` (wrapped) | `find -print` fallback | |
| `attrib` | `Get-ChildItem` → perms | `ls -la` | |
| `clip` | `Set-Clipboard` | `xclip`/`wl-copy` | WIN+V menu |
| `pwd`/`cd` | native | native | |
| `xcopy` | `robocopy`-ish `copy -r` | `cp -a --reflink=auto` | trap: no `-a` on Windows — now it exists |

### 2.2 Processes & services
| Windows | PowerShell | Linux | Notes |
|---|---|---|---|
| `tasklist` | profile fn (DRY table) | `ps -eo …` | reformatted columns |
| `taskkill /F /PID n` | `Stop-Process -Id n` | `kill -9` | |
| `Get-Process` | native pwsh | `ps` | auto-mapped type names |
| `sc query` | profile fn | `systemctl status` | |
| `services.msc` | `settingsctl services` | `systemctl list-units` | GUI too |
| `runas /user:USER cmd` | profile fn | `sudo -u USER` | password via PAM |

### 2.3 Networking
| Windows | PowerShell | Linux | Notes |
|---|---|---|---|
| `ipconfig` | profile fn (summary) | `ip -brief addr/route` | |
| `netstat -ano` | `ss -tulpn` | same | PID column shown |
| `ping` | native | native | |
| `tracert x` | `traceroute` | same | strips flags |
| `nslookup x` | `dig +short` | same | |
| `netsh` | profile fn → `ip`/`nmcli` | `nmcli` | network manager |
| `route print` | `ip route show` | same | |
| `arp -a` | `ip neigh` | same | |
| `Get-NetIPAddress` | native pwsh→ip | `ip addr` | via Microsoft shim |

### 2.4 Text & system
| Windows | PowerShell | Linux | Notes |
|---|---|---|---|
| `cls` | `Clear-Host` | `clear` | |
| `echo` | native | native | |
| `findstr` | `Select-String` | `grep` | `findstr /i` → `grep -i` |
| `more` | native | native | |
| `sort` | native | native | |
| `where` | `Get-Command` | `type -a` | |
| `ver` | `$PSVersionTable` | `uname -a` | Obsidian banner |
| `msinfo32` | `settingsctl sysinfo` | `inxi -F` | GUI page |
| `notepad` | profile fn | `code`/`nvim`/`nano` | preferred editor config |
| `explorer` | `obsidian-files` | `xdg-open .` | the "file explorer" |
| `control` | `settingsctl` | `gnome-control-center`-ish | Obsidian Settings |

### 2.5 macOS (both shells)
| macOS | Map to |
|---|---|
| `open x` | `xdg-open x` |
| `pbcopy` / `pbpaste` | `wl-copy` / `wl-paste` |
| `say text` | `espeak` or obsidian-ai tts |
| `brew install p` | `pkg install p` |
| `defaults read` | `dconf read` |
| `cmd+c/v` everywhere | native Wayland clipboard |

## 3. `pkg` unified package manager (spec)

```
pkg search <q>          # apt+flatpak+snap+appimage+repo index; AI top-3 with reasons
pkg install <p>         # resolves provider: flatpak > deb > appimage > snap > source
pkg update              # channel update (rolling/stable per profile)
pkg upgrade
pkg remove <p>
pkg list [--external]
pkg info <p>
pkg sources             # apt repos, flatpak remotes, appimage buckets, GitHub store
pkg install-from <url>  # GitHub store: clone→build-in-Cell→sandbox-install (Agent Hub)
pkg -g <q>              # opens App Store GUI pre-searched
```
Backends: Debian `apt`, Arch `pacman` (channel), `flatpak` (default sandbox),
`appimage`/`deb`/`snap` for third parties; `chezmoi` for dotfile/managed config.
AI search runs offline via `obsidian-ai` (or provider) and only *suggests*;
installation always requires a human token.

## 4. Verdict / acceptance

- [ ] `dir` in pwsh and bash both show file listings with hidden files.
- [ ] `tasklist` columns correct; `sc status` returns systemd state.
- [ ] `ipconfig`/`netstat -ano`/`tracert` work in both shells.
- [ ] `pkg search "pdf editor"` returns a typed suggestion and installs it.
- [ ] `bash` inside pwsh and `pw` inside bash both work (no recursion traps).