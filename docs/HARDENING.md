# Obsidian OS — Hardening Checklist (CIS-mapped)

Reference: **CIS Debian Linux 12 Benchmark v1.0** — column "CIS" is the benchmark
section; "OWL" is Obsidian's default (check it live with `securityctl status`).
Levels: **L1** (safe everywhere) / **L2** (defense-in-depth; some opinions) / **Ghost** (privacy/anti-forensic tier).

Legend: ✅ default-on · ⚙ configurable (GUI/securityctl) · ⛔ off unless explicitly enabled

| CIS § | Control | OWL default | Level | Where |
|---|---|---|---|---|
| 1.1.1 | Disable unused filesystems (cramfs, freevaxfs, jffs2, hfs*, udf, usb-storage L2) | ✅ blocked via `install` lines in modprobe conf | L1 | `/etc/modprobe.d/obsidian-hard.conf` |
| 1.1.2 | Separate `/tmp`, `/var`, `/var/tmp` (nodev,nosuid,noexec) | ✅ tmpfs `/tmp` nodev,nosuid,noexec | L1 | fstab/`systemd` tmp.mount |
| 1.1.x | Additional filesystems & mount opts | ✅ `noexec` on /var/tmp, bind hardening | L1/L2 | fstab |
| 1.2 | Package repos GPG, disable unused features | ✅ signed `deb` repos, `unattended-upgrades` on | L1 | apt/dpkg |
| 1.3 | Filesystem integrity (AIDE) | ✅ AIDE-init at firstboot, daily `.timer` | L1 | `obsidian-aide.timer` |
| 1.4 | bootloader (GRUB/UKI) — password, mode | ✅ systemd-boot + shim, no recovery shell, SB | L1 | boot |
| 1.5 | Additional (ASLR, ptrace, coredumps, kexec, kernel panic) | ✅ `kernel.randomize_va_space=2`, `ptrace_scope=1`, `fs.suid_dumpable=0`, `kexec_load_disabled=1` | L1 | `99-obsidian-hardened.conf` |
| 1.6 | Secure Boot + kernel lockdown | ✅ SB enrolled; `lockdown=integrity` at boot (confidentiality on Ghost) | L2 | cmdline |
| 1.7 | Warning banners | ✅ DOJ-style `motd` + `/etc/issue` | L1 | files |
| 2.1 | inetd/xinetd not installed | ✅ removed from base | L1 | apt |
| 2.2 | Disable insecure services (telnet, rsh, rlogin, tftp, ftp…) | ✅ all removed; sshd only when authorized | L1 | apt/systemd |
| 2.2 | OpenSSH hardened | ⚙ Server profile: key-only, `PermitRootLogin no`, `MaxAuthTries 3` | L1 | sshd config |
| 2.2 | disable `avahi-daemon` | ✅ masked (needed?) → masked by default | L1 | systemd |
| 2.2 | clock/client: chrony/systemd-timesyncd | ✅ timesyncd on | L1 | systemd |
| 2.3 | CUPS only if printing | ⛔ off by default | L1 | |
| 2.4 | ntp, dovecot, httpd… | ⛔ server roles explicit (Server Hub) | L1 | |
| 3.1 | TCP wrappers removed; no rservices | ✅ (no r-services provisioned) | L1 | |
| 3.2 | network kernel params (CIS 3.2.1–3.2.8) | ✅ ip_forward=0, source route off, redirects off, rp_filter=1, syncookies | L1 | sysctl |
| 3.3 | IPv6 disabled or hardened | ✅ IPv6 present + address randomization; Ghost disables v6 | L1/L2 | sysctl |
| 3.4 | Uncommon protocols (dccp, sctp, rds, tipc) | ✅ blocked via modprobe conf | L1 | |
| 3.5 | Uncommon net protocols off; nftables active | ✅ nftables default-deny input | L1 | `nftables.conf` |
| 3.6 | tcpwrappers/USB storage L2 | ✅ `usb-storage` blocked on Server/Ghost | L2 | modprobe |
| 4.1.x | auditd | ⚙ Hardened/Ghost: `audit=1` kernel arg, rules in `/etc/audit/rules.d/` | L2 | |
| 4.2.x | journald + logrotate | ✅ systemd-journald (volatile on Ghost), `MaxFileSec` set | L1 | journald conf |
| 4.3 | core dumps, apport | ✅ coredump=0, no crash dumps persist (tmpfs on Ghost) | L1 | sysctl/coredump.conf |
| 5.1.x | AIDE, cron perms | ✅ covered 1.3; cron.d lockdowns | L1 | |
| 5.2.x | SSH server hardening | ⚙ see 2.2 | L1 | |
| 5.3 | PAM + password quality | ✅ `pwquality` min length; yescrypt hash | L1 | pam |
| 5.4 | user/group ownership, umask 027 | ✅ login.defs umask 027, no world-writable homes | L1 | login.defs |
| 5.5 | sudoers strict (`NOPASSWD` avoided) | ✅ admin password required (Firstboot), sudoers.d dropin | L1 | sudoers |
| 5.6 | PAM limits and account lockdown | ✅ faillock 5 attempts, `pam_faillock` | L1 | pam |
| 6.1 | Verify system file permissions / world-writable | ✅ `dpkg-statoverride`, scan at AIDE run | L1 | aide |
| 6.2 | User dotfiles perms (600) | ✅ wizard applies at user create | L1 | |
| 6.3 | Pending updates / security updates | ✅ `unattended-upgrades` on security-only (Server) | L1 | apt |
| 7.1-7.x | Site policy / warning banners | ✅ banner + `issue` | L1 | |

## Obsidian beyond CIS (L2 / Ghost / hardening tiers)

| Area | Control | Status |
|---|---|---|
| Kernel | hardened *config*: hardened allocator (`SLAB_FREELIST_RANDOM/HARDENED`, `INIT_ON_ALLOC/FREE`, `PAGE_POISONING`), memory protection (`STRICT_KERNEL/MODULE_RWX`, `VMAP_STACK`, `RANDOMIZE_KSTACK_OFFSET`, `STACKPROTECTOR_STRONG`, `FORTIFY`, `HARDENED_USERCOPY`), lockdown LSM, `MODULE_SIG` (auto-generated cert, `MODULE_SIG_ALL`), `IO_URING`(+ its only `select`ing driver `BLK_DEV_UBLK`)/`KEXEC`/`HIBERNATION` off | ✅ base (task 1.7, `scripts/build-kernel.sh` + `hardened.config`) |
| Kernel | `lockdown=confidentiality`, `dmesg_restrict=1`, `kptr_restrict=2`, `perf_event_paranoid=3` | ✅ base (Ghost: confidentiality) |
| Kernel | signed modules only (custom MOK, `module.sig_enforce`) | ⚙ Hardened |
| MAC | AppArmor enforce for obsidian services + profiles for browsers/cells | ⚙ Hardened |
| MAC | SELinux optional profile (Fedora-style) | ⛔ opt (roadmap) |
| Sandbox | every installed app in a bubblewrap Cell by default | ✅ base |
| Sandbox | KVM disposable VMs (Qubes-style) | ⚙ Cells `--vm` |
| Network | nftables default-deny inbound; egress Dock per profile | ✅ base |
| Network | Suricata IDS inline (drops on alert for L2) | ⚙ Hardened |
| Network | DNS-over-TLS/HTTPS; DNSSEC allow-downgrade | ✅ base |
| Network | random MAC per network; per-boot spoof (Ghost) | ✅ base / ⚙ Ghost |
| Network | Transparent Tor + kill switch | ⚙ Ghost/Pentester |
| Devices | **USBGuard** allowlist (default-deny new USB) | ⚙ Hardened/Server |
| Malware | **ClamAV** scheduled scan (optional, on-demand by default) | 🔶 optional |
| Storage | LUKS2 (Argon2id) root//home//varlib | ✅ install |
| Storage | TPM2 auto-unlock + measured boot | ⚙ firstboot |
| Storage | dm-verity on /usr (Advanced) | ⛔ L2 opt |
| Storage | encrypted zram, no disk swap | ✅ |
| Events | auditd rules: execve, mount, time, MAC changes | ⚙ Hardened/Ghost |
| Integrity | fapolicyd allowlist | ⚙ Hardened |
| Injection | sysctl `ptr_restrict` etc + hardened GCC flags on all obsidian pkgs | ✅ build flag policy |
| Supply | signed repo, checksum+SB verification of ISOs, reproducible builds | ✅ CI |

### How to verify (one-liners)
```bash
securityctl status                      # posture + module states
nft -c -f /etc/nftables.conf && echo OK # firewall parse
aa-status | head -30                    # AppArmor profiles
systemctl is-active obsidian-aide.timer # FIM
journalctl -b --no-pager | grep -c auditd # audit events
cryptsetup luksDump /dev/sda2 | head   # LUKS2 + Argon2id
```

### Exception notes
- Wireless monitor mode requires explicit per-session grant (Pentester profile).
- Server profile intentionally opens whitelisted ingress for enabled roles.
- Ghost trade-offs are documented honestly: cannot guarantee anonymity, only
  reduces surface + residue.