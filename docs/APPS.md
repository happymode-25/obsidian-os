# Obsidian Apps — combined design index

Full designs: `apps/security-center/README.md` · `apps/ai-assistant/README.md`.
This file adds the remaining Windows-like app mockups (Start, Files, Settings,
App Store, Firewall UI, Server Hub) + the tech-stack rule.

## Tech-stack rule (every app)
- **GUI:** GTK4 + libadwaita, Window is a "page" in the Shell panel hierarchy;
  keyboard-first; dark/light/Windows theme inherited from `obsidian-theme`.
- **CLI twin:** each app has `<app>ctl` (e.g. `filesctl`, `settingsctl`,
  `storectl`, `firewallctl`, `serverctl`, `vmctl`, `nasctl`, `agentctl`).
- **Actual work:** a small Rust/Go service (Command pattern), GUI is a thin
  client — so headless server profiles still get the same CLI.
- **Sandbox:** launched through Cells unless granted otherwise.

## Start menu (shell/start)

```
Win              ┌─ Obsidian Start ───────────────────────────┐
                 │  🔍 search… (files · apps · pkg · AI)       │
                 │  Pin  [Files][Terminal][Nvim][Firefox]     │
                 │       [AI][SecurityCtr][Store][Settings]   │
                 │  Recent ▸ report.pdf  scan.sh  HACKME.md   │
                 │  ──────────────────────────────────────────│
                 │  User:● obsidian  [Power][Lock] [Restart]  │
                 └────────────────────────────────────────────┘
```

## Files ("Explorer")

- Ribbon: back/forward · up · breadcrumbs · search bar; right side quick access
  (Home, Documents, Download, Recent, Network).
- Tabs; drag-and-drop everywhere; column/icon/list views; context menus with
  "Open in Terminal", "Scan with Security Center", "Send to Vault", "Share
  (NAS)".
- CLI twin opens the same path: `filesctl open ~/Documents`.

## Settings ("Control Panel")

- Searchable categories mirroring Windows: System, Display, Personalization,
  Accounts, Time & language, Network & Internet, Bluetooth & devices, Apps,
  Gaming, Privacy & security, Update. Layout is a sidebar (like Win11).
- Power/Lockdown toggles write the posture files consumed by sysctl/nft.

## App Store (`obsidian-store`)

- Cards from flatpak + GitHub store + apt channels; category rail; "installed"
  badges; "Update all"; ratings = local curation (no telemetry).
- `storectl install <id>` / `storectl update` / `storectl export manifest.json`.

## Firewall UI

- Inbound/Outbound grids (like Windows Defender Firewall w/ Advanced), profiles
  (Public/Private: Standard/Hardened/Ghost), one-click enable a server role
  (adds the exact `tcp dport` accept chain), parse-test each rule via `nft -c`.

## Server Hub

- Role cards (Web/Databases/Containers/VMs/NAS/Proxy/SSH/DNS/Gateway): switch on
  = writes config + firewall rule + unit start; health panel; live logs tail;
  storage & snapshot view. All via `serverctl`.

## Agent Hub

- Tabs: My agents · Browse (GitHub store) · Automations (n8n/Flowise/Dify).
  Install-by-URL field with build pipeline preview and sandbox toggle.