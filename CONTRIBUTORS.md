# Contributors

The monorepo's git history uses a single canonical committer identity
(`Obsidian OS <obsidian@localhost>`), so *who* contributed *what* is
recorded here instead of in commit authorship.

## Contribution streams

| Stream | What it covers |
|---|---|
| **Core OS (maintainer)** | Debian-based distribution build: hardening config, ISO pipeline, kernel packaging (Task 1.7), gap reports |
| **redteam-agents harness** | Multi-agent pentest/VA framework: safety-first pipeline, egress firewall, scope enforcement, evidence standard, lab + eval harness, Phase-4 ops (budgets, drift, tickets, review, HTML reports, engagement model) |
| **Repo & CI maintenance** | License attribution, CI workflows, test-suite gates, acks |

## Adding yourself

If you contributed code, docs, tests, review, or operational feedback:

1. Fork, add a row to the table above (your handle + a one-line summary).
2. Commit with `git log --format='%an'`-neutral identity if you prefer the
   canonical committer (see `CONTRIBUTING.md` for the no-claims-without-proof
   rule).

Pull requests that change attribution must be authored by the credited
person or reference their approval.
