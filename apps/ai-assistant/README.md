# Obsidian AI Assistant — design

**Type:** system-wide sidebar (like Copilot) + CLI (`obsidianai`) + DBus service
(`obsidian-ai`). **Runtime:** local-first (Ollama) with a provider gateway.

```
┌──────────────────────── VT-100-style OBSIDIAN AI ──────────────────────┐
│  Ctrl+Space              [Chat|Agent|Plan]   [nvim] [local qwen3]      │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ you: install me a PDF editor                                    │   │
│  │ obs.: I found 3 matches → flatpak: okular (recommended), …      │   │
│  │       Run: pkg install okular      [Preview] [Approve] [Deny]    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  Context: shell cwd, files open, active app tab, OS state (read-only) │
│  Approval gate: every terminal command needs human approval unless    │
│  the user has granted a scoped trust (e.g. "pkg install *").          │
└────────────────────────────────────────────────────────────────────────┘
```

## 1. Modes
- **Chat** — RAG over local docs (`~/Documents`, notes, man pages); answers cite
  sources; offline by default.
- **Agent** — multi-step task; builds a step list; each step with terminal
  commands is executed ONLY after `[Approve]` (polkit-style dialog); steps are
  recorded for replay/rollback.
- **Plan** — deep-work planning without execution: research, weigh options,
  emit an executable markdown plan with rollback checkpoints.

## 2. Provider gateway (`obsidian-ai`)
| Provider | Notes |
|---|---|
| Local (Ollama) | qwen3 / llama3.x / mistral — default, offline |
| vLLM / llama.cpp server | power users, self-host |
| OpenAI / Anthropic / Gemini / Groq / Mistral / Cohere / DeepSeek / Together | optional, per-provider key vault (libsecret) |
| HackBot-style multi-LLM | rerank + ensemble when enabled |

Provider abstraction = one `chat()` API + context packer; models behind a
routing score (latency × privacy × cost). Ghost profile hard-restricts to local.

## 3. Agent orchestrator (vendored, offline)
- Adapter for **CrewAI-style crews** and **AutoGPT-style autonomous loops**,
  shipping as a Go/Rust worker (`obsidian-agentd`) + Python runtime for the
  agent definitions. Runs in its own Cell; every shell escape approved as above.
- Agents: `automation` (repeat tasks, cron via systemd timers), `security`
  (drives `securityctl`, writes report skeletons), `osint` (harvest →
  normalized findings), `sysadmin` (health, upgrades deltas), `coding`
  (edit files in a branch, run tests, propose merge).

## 4. Agent Hub
- GUI to browse/install `n8n`, `Flowise`, `Dify`, `AutoGPT`-style frameworks,
  **or any GitHub repo by URL** → `agentctl install <url>` clones into a Cell,
  detects build (Containerfile/flatpak/docker-compose/package.json/Pipfile),
  builds, registers with `obsidian-agentd`, sandboxed, auto-updated.

## 5. System hooks
- **Log analysis:** assistant can read non-sensitive log shards (with permission)
  and produce threat summaries for the Security Center.
- **Code completion:** in the built-in editor (LSP + local model for the
  completion stream), plus `codex-style` chat in the editor.
- **Report generation:** pentest reports from tool outputs via a template
  renderer (Markdown/PDF in the vault).

## 6. CLI parity
```
obsidianai ask <q>
obsidianai chat --mode agent --task "scan this host, write report"
obsidianai plan "harden this server"          # Plan mode, no execution
obsidianai agent list | agent start coding
obsidianai approve <task-id> | agentctl install <github-url>
```

## 7. Verify (acceptance)
- [ ] Local model answers offline; provider switch works.
- [ ] `ask "install me a PDF editor"` → `pkg` suggestion with Approve/Deny.
- [ ] Agent run: every command approval-gated; rollback works; log written.
- [ ] Security Center can summon the assistant for a threat summary.