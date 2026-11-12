# Issue Management

Rules: `agent-config/rules/issue-hygiene.md`. Labels: `.github/labels.yml` →
`./scripts/sync_labels.sh`.

## Kind of work

The repository is personal, so GitHub Issue Types are unavailable; the title's Conventional-Commits
`<type>` (`feat`, `fix`, `chore`, `docs`, …) carries the kind of work. A milestone is an issue titled
`epic: <milestone>` whose sub-issues hold the work.

## Labels

| Group      | Labels                                                                                   |
| ---------- | ---------------------------------------------------------------------------------------- |
| Priority   | `priority:P0` (broken main / wrong PASS) · `P1` (this week) · `P2` (this milestone) · `P3` (backlog) |
| Area       | `area:ir` `area:loader` `area:modes` `area:checks` `area:report` `area:cli` `area:render` `area:examples` `area:ci` `area:docs` `area:agents` |
| Status     | `status:needs-triage` `status:blocked` `status:deferred`                                 |
| Resolution | `duplicate` `wontfix`                                                                    |
| Community  | `good first issue`                                                                       |

A wrong `PASS` (the verifier claims something holds when it does not) is always `priority:P0`.

## Epics

One Epic per roadmap week (`docs/ROADMAP.md`); each check routine is one sub-issue.
