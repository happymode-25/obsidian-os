# Obsidian OS — Legal & Ethical Guardrails (READ BEFORE ENABLING TOOLING)

## 1. Positioning
Obsidian OS is a general-purpose operating system that *includes* and *integrates*
offensive/dual-use security tooling. Owning such a toolbox is legal in most
jurisdictions; **using it without authorization is a crime** (CFAA-style statutes,
EU cybercrime directive, Computer Misuse Act, and equivalents). This project does
not grant authorization — only the system owner's written scope does.

## 2. Hard rules enforced by the OS, not just docs

| Rule | Enforcement |
|---|---|
| Offensive tools ship **disabled** | default state in `manifests/tools.yaml` = `disabled`; launchers will not run |
| Enable requires a Pentester (or Server+redteam) **profile** | enforced by `securityd` posture check |
| **Per-tool authorization** must be granted | consent ledger (`consent.json`, chained hashes) |
| Consent step is explicit | first-boot wizard checkbox: "I will only use these tools on systems I own or have written authorization to test." — declining installs them *disabled* |
| Revocation is immediate | `securityctl consent revoke --all` kills tools + closes Cells |
| C2-lab tools run **network-isolated** | Cells with no external egress (see `pentester.yaml` lab_cells) |
| Wireless monitor mode needs per-session grant | netlink cap gated per session |
| Everything is audited | execve/consent/launch events → `auditd` + ledger |

## 3. Per-category notes
- **Scanners (nmap/nuclei/zap):** passively probing a system you don't own may
  still violate law; scope is essential.
- **C2 / post-exploitation (mythic/havoc/sliver/metasploit):** these are
  intruder-simulation tools. We restrict them to the isolated lab network.
- **Credential tools (hashcat/john):** fine on hashes you own (your own
  password audits). Exfil/rainbow misuse is on the operator.
- **Wireless (aircrack/kismet):** monitor-mode use is regulated in many
  jurisdictions (France, Germany, parts of the US, etc.); you are responsible
  for legal monitor-mode use.
- **OSINT:** TheHarvester/Amass/SpiderFoot are legal for open data; scraping
  some sites may breach their ToS. Be mindful.
- **Hardware (Flipper/Bus Pirate/Marauder):** transmitting on reserved bands is
  regulated; usage varies wildly by country.

## 4. Honest limitations (anti-forensics cannot be absolute)
- **Ghost mode reduces residue, it does not guarantee anonymity.** Memory wipe
  is best-effort (we run from that memory); persistent media beyond the vault is
  the user's responsibility (we recommend leaving the vault on removable media).
- **Tor is not infallible.** Traffic analysis, exit-node compromise, and operator
  mistakes still leak. Obsidian's kill switch stops *our* leaks; it cannot stop
  deliberate user errors.
- **Anti-forensics ≠ evidence destruction is allowed.** Do not use Ghost mode to
  destroy evidence you are legally obligated to preserve. This tool does not
  provide legal advice.

## 5. Export control & sourcing
- Some tools (e.g., certain crypto/strong-encryption UIs; export-restricted
  toolchains) may be regulated by **dual-use export controls** (Wassenaar /
  EAR). Obsidian ships open-source software you can obtain legally where you're
  located; the project itself is unregulated open source, but *you* are
  responsible for your jurisdiction's import/export rules.
- `binary-ninja` ships **only if licensed**, and license validation is performed
  before installation.

## 6. Authorship & support
- Tool licenses are the respective upstream projects'; Obsidian bundles them
  under their own licenses (GPL/BSD/Apache/etc.). The store UI shows the SPDX
  ID per tool.
- We accept responsible-disclosure reports for Obsidian itself
  (`security@obsidian.local` — reachable only when a mail service is enabled).

## 7. Project policy for the repo
1. No malware/weaponized payloads committed to this repository — the *tooling*
  is catalogued (URL + install method) and acquired at firstboot from upstream.
2. No credential harvesting *targets* are shipped; test fixtures are clearly
  synthetic and in `testlab/`.
3. All profiles gated as above; the consent state machine is unit-tested.

## 8. Final word
> A security tool in competent, honest hands shortens incident response, proves
> compliance, and hardens the internet. In dishonest hands it is a crime weapon.
> **Obsidian is the former by construction.** If you do not own (or hold written
> authorization for) the systems you plan to test, stop now and uninstall the
> pentester profile.