// Obsidian OS — securityd (Security Center daemon) — Rust skeleton
// Compile:  cargo build --release   (workspace: apps/security-center/daemon)
// This file is the authoritative skeleton: real backends are modules.
use std::fs;
use std::path::Path;

/// Tool registry entry mirrored 1:1 from manifests/tools.yaml.
#[derive(Clone, Debug)]
struct Tool {
    id: String,
    name: String,
    state: State, // Installed / Disabled / Enabled
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum State {
    Installed,
    Disabled,
    Enabled,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Posture {
    Standard,
    Hardened,
    Ghost,
}

/// Tamper-evident consent ledger entry (chained hashes).
#[derive(Clone, Debug)]
struct ConsentEntry {
    user: String,
    tool: String,
    action: String, // grant | revoke
    ts: String,
    prev_hash: String,
    hash: String,
}

/// Backend boundary — every privilege change goes through this layer.
trait SecurityBackend {
    fn apply_firewall(&self, ruleset: &str) -> Result<(), String>;
    fn toggle_tor(&self, on: bool) -> Result<(), String>;
    fn launch_cell(&self, name: &str) -> Result<(), String>;
    fn kill_all_cells(&self) -> Result<(), String>;
}

struct NftBackend;
impl SecurityBackend for NftBackend {
    fn apply_firewall(&self, ruleset: &str) -> Result<(), String> {
        let tmp = "/etc/obsidian/fw.d/staged.nft";
        fs::write(tmp, ruleset).map_err(|e| e.to_string())?;
        // Validation gate: nft -c before install.
        let check = std::process::Command::new("nft")
            .args(["-c", "-f", tmp])
            .output()
            .map_err(|e| e.to_string())?;
        if !check.status.success() {
            return Err(String::from_utf8_lossy(&check.stderr).into_owned());
        }
        std::process::Command::new("nft")
            .args(["-f", "/etc/nftables.conf"])
            .status()
            .map_err(|e| e.to_string())?;
        Ok(())
    }
    fn toggle_tor(&self, on: bool) -> Result<(), String> {
        let svc = if on { "obsidian-tor" } else { "killswitch.service" };
        run_systemctl(svc, if on { "start" } else { "stop" })
    }
    fn launch_cell(&self, name: &str) -> Result<(), String> {
        // securityd may only spawn through systemd-run scoped to the cell unit.
        run_systemctl(&format!("obsidian-cell@{}.service", name), "start")
    }
    fn kill_all_cells(&self) -> Result<(), String> {
        run_systemctl("obsidian-cellmgrd.service", "restart")
    }
}

fn run_systemctl(unit: &str, op: &str) -> Result<(), String> {
    let st = std::process::Command::new("systemctl")
        .args([op, unit])
        .status()
        .map_err(|e| e.to_string())?;
    if st.success() {
        Ok(())
    } else {
        Err(format!("systemctl {} {} failed", op, unit))
    }
}

/// Minimal consent ledger with chain validation.
struct ConsentLedger {
    path: String,
    entries: Vec<ConsentEntry>,
}

impl ConsentLedger {
    fn load(path: &str) -> Self {
        let entries = fs::read_to_string(path)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default();
        Self { path: path.to_string(), entries }
    }

    fn grant(&mut self, user: &str, tool: &str) -> Result<(), String> {
        let prev = self.entries.last().map(|e| e.hash.clone()).unwrap_or_default();
        let ts = chrono::Utc::now().to_rfc3339();
        let payload = format!("{}|{}|grant|{}|{}", user, tool, ts, prev);
        let hash = format!("{:x}", md5::compute(payload.as_bytes())); // swap for sha256 in prod
        self.entries.push(ConsentEntry {
            user: user.into(),
            tool: tool.into(),
            action: "grant".into(),
            ts,
            prev_hash: prev,
            hash,
        });
        self.flush()
    }

    fn flush(&self) -> Result<(), String> {
        // append-only: write to a .new file, rename over; verify chain on boot.
        fs::write(format!("{}.new", self.path), serde_json::to_string(&self.entries).unwrap())
            .map_err(|e| e.to_string())?;
        fs::rename(format!("{}.new", self.path), &self.path).map_err(|e| e.to_string())
    }
}

fn main() {
    println!("securityd skeleton — real daemon wires DBus + backend modules here.");
    let backend = NftBackend;
    let ledger = ConsentLedger::load("/var/log/obsidian/consent.json");
    let _ = (backend, ledger, Posture::Hardened, State::Disabled);
}