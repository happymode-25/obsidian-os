# Obsidian Security Center — design

**Type:** GUI-first unified launcher + management console for the entire security
stack and tool suite. **CLI twin:** `securityctl`. **Daemon:** `securityd` (Rust).

## 1. Architecture

```
┌──────────────────────── Security Center (GTK4) ────────────────────────┐
│ Header: posture badge · posture switcher · consent status · upgrade    │
│ Tabs:  Dashboard | Tools | Firewall | IDS | Integrity | Tor/Vault |    │
│        Cells | Consent | Reports                                       │
└──────────────┬─────────────────────────────────────────────────────────┘
               │ DBus (org.obsidian.SecurityCenter1)
┌──────────────▼─────────────────────────────────────────────────────────┐
│ securityd (Rust)                                                       │
│  • state + consent ledger (append-only, tamper-evident)                │
│  • tool registry  <- manifests/tools.yaml (installed/enabled/disabled) │
│  • module backends: nftables / suricata / aide / tor / veracrypt /     │
│    cells (bubblewrap) / mac-spoof / audit                             │
└──────────────┬─────────────────────────────────────────────────────────┘
               │
  ┌────────────┼──────────────┐──────────────┐─────────────┐
  ▼            ▼              ▼              ▼             ▼
 nft          suricata       aide          tor            cells
firewall       IDS            FIM         kill switch    sandboxes
```

- Frontend: **GTK4 + libadwaita**; live data via DBus signals (no polling).
- Backend: **Rust** `securityd`; all privilege escalation through its single
  polkit-credentialed service — GUIs and CLIs never hold root.
- Each tool in `tools.yaml` renders as a **card** in the Tools tab: state chip
  (`installed/disabled/enabled`), one-click `enable`, path to its Cell, "launch"
  (spawns the tool inside its bubblewrap Cell), auto-update status.

## 2. UI mockup (text)

```
┌─ Obsidian Security Center ────────────────────────────────  [×] ─┐
│ ● POSTURE: HARDENED   [Switch…]  Consent: ✓ granted (pentester)   │
│ ┌─────────────────────────────────────────────────────────────┐   │
│ │ Dashboard                                                   │   │
│ │  Firewall ........... ACTIVE   (nft, 4 rulesets)             │   │
│ │  IDS (Suricata) ..... ACTIVE   drops 12 · alerts 3 (today)    │   │
│ │  FIM (AIDE) ......... PASS     1h ago · 61,204 files         │   │
│ │  Tor ................ STANDBY   (Ghost only)                 │   │
│ │  Cells .............. 4 locked · 1 open (scan)               │   │
│ │  Vault .............. closed                                 │   │
│ │  Consent ledger ..... 8 grants · 2 revoked                   │   │
│ └─────────────────────────────────────────────────────────────┘   │
│ [Tools] nmap ▸ nmap           States: ▸ disabled  ▸ consent      │
│ [Tools] zap   ▸ OWASP ZAP     "needs per-tool consent (pentest)"   │
│ [Firewall]  inbound ▸ default deny   rules table editable          │
│ [Consent]   tool ▸ grant/revoke      "zap"   status: granted       │
└────────────────────────────────────────────────────────────────────┘
```

## 3. CLI parity (`securityctl`)

```
securityctl status
securityctl posture set hardened|ghost|standard
securityctl firewall list | add drop tcp dport 8443 | save
securityctl ids status | alert list
securityctl fiw status
securityctl tor engage | disable            (Ghost)
securityctl cell launch scan | cell close scan
securityctl consent grant zap | consent revoke --all | consent ledger
securityctl tool install nmap | tool enable nmap | tool update-all
securityctl report nightly                     (-> Obsidian Reports)
```

## 4. Consent ledger (security requirement)

- Written to `/var/log/obsidian/consent.json` via `securityd`; append-only;
  hashed chain (each entry carries prev-hash + user + action + timestamp) so
  it is tamper-evident like a mini-blockchain.
- Revocation takes effect immediately: tools are killed, Cells closed, and the
  Security Center flips to "not authorized".

## 5. Module map → brief

| Brief item | Module | Backend |
|---|---|---|
| firewall (nftables + GUI) | Firewall | `nft` via libnftnl wrapper |
| IDS/IPS | Suricata dashboard | suricata + eve.json reader |
| FIM | AIDE | aide, DB-backed |
| MAC randomization | MAC spoof | NetworkManager dispatch + `macchanger` |
| VPN chain | VPN/Tor | wireguard-tools + tor |
| encrypted vault | Vault | libVeraCrypt / cryptsetup |
| sandboxed apps | Cells | bubblewrap (systemd-run -p ...) |
| amnesic/live mode | Ghost | live-initrd overlays |

## 6. Build & verify

- `cargo build --release` → `securityd`; `meson build` → GTK4 app.
- Unit tests: ruleset generator round-trip (`nft -c`), consent ledger invariants.
- Acceptance: a Podman-wirelab "red team walkthrough" — nmap → nuclei → zap →
  report; every action gated and logged; revocation kills running tools.