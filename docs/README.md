# Prescript Documentation

> Index of every file under `docs/`. `tests/test_docs_index.py` fails CI when a doc is added
> without an entry here.

| Document                                     | Purpose                                                   | Audience              |
| -------------------------------------------- | --------------------------------------------------------- | --------------------- |
| [ARCHITECTURE.md](./ARCHITECTURE.md)         | Pipeline, IR, module boundaries, design decisions         | Everyone (read first) |
| [PRESCRIPT-LANGUAGE.md](./PRESCRIPT-LANGUAGE.md)       | Netlist grammar v0.2 (SSOT; the loader implements it)     | Authors / developers  |
| [CHECKS.md](./CHECKS.md)                     | Assertion routines: semantics, args, status per case      | Authors / developers  |
| [ROADMAP.md](./ROADMAP.md)                   | Winter PoC milestones, scope, out-of-scope, demo script   | Everyone              |
| [PROPOSAL-BEHAVIOUR-LAYER.md](./PROPOSAL-BEHAVIOUR-LAYER.md) | Proposal (not implemented): `kinds:`, `sequences:`, transition assertions | Authors / developers |
| [DEVELOPMENT.md](./DEVELOPMENT.md)           | Setup, commands, hooks, CI                                | Developers / agents   |
| [ISSUE_MANAGEMENT.md](./ISSUE_MANAGEMENT.md) | Labels, Issue Types, epics                                | Developers / agents   |

Agent rules live in `agent-config/rules/` (SSOT) and are summarised in the root `AGENTS.md`.
