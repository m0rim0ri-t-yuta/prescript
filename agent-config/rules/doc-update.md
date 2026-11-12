---
paths:
  - 'docs/**'
  - 'AGENTS.md'
  - 'agent-config/**'
  - '.agents/skills/**'
  - 'src/keel/loader.py'
  - 'src/keel/ir.py'
  - 'src/keel/checks/**'
---

# Documentation Update Discipline

When code changes documented behaviour, update the docs in the **same PR**.

| Change                              | Update                                   |
| ----------------------------------- | ---------------------------------------- |
| Netlist grammar / loader behaviour  | `docs/KEEL-LANGUAGE.md`                  |
| IR, pipeline stage, module boundary | `docs/ARCHITECTURE.md`                   |
| New/changed assertion routine       | `docs/CHECKS.md`                         |
| Tooling, dependency, command        | `docs/DEVELOPMENT.md`                    |
| Scope or milestone                  | `docs/ROADMAP.md`                        |
| Project-wide agent policy           | `AGENTS.md`                              |
| Agent rule                          | `agent-config/rules/*.md` (one concern)  |

Every file under `docs/` is listed in `docs/README.md`; `tests/test_docs_index.py` fails otherwise.

SSOT hierarchy: `AGENTS.md` + `agent-config/rules/*.md` → `.agents/skills/*/SKILL.md` →
`docs/*.md`.
