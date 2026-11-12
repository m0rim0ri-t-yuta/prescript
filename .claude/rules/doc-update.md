---
paths:
  - 'docs/**'
  - 'AGENTS.md'
  - 'agent-config/**'
  - '.agents/skills/**'
  - 'src/prescript/loader.py'
  - 'src/prescript/ir.py'
  - 'src/prescript/checks/**'
---

<!-- GENERATED from agent-config/rules/doc-update.md by scripts/sync_agent_config.py. Edit the source. -->

# Documentation Update Discipline

When code changes documented behaviour, update the docs in the **same PR**.

| Change                              | Update                                   |
| ----------------------------------- | ---------------------------------------- |
| Netlist grammar / loader behaviour  | `docs/PRESCRIPT-LANGUAGE.md`                  |
| IR, pipeline stage, module boundary | `docs/ARCHITECTURE.md`                   |
| New/changed assertion routine       | `docs/CHECKS.md`                         |
| Tooling, dependency, command        | `docs/DEVELOPMENT.md`                    |
| Scope or milestone                  | `docs/ROADMAP.md`                        |
| Project-wide agent policy           | `AGENTS.md`                              |
| Agent rule                          | `agent-config/rules/*.md` (one concern)  |

Every file under `docs/` is listed in `docs/README.md`; `tests/test_docs_index.py` fails otherwise.

SSOT hierarchy: `AGENTS.md` + `agent-config/rules/*.md` → `.agents/skills/*/SKILL.md` →
`docs/*.md`.
