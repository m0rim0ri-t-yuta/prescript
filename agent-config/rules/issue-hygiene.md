# Issue Hygiene (Creation & Triage)

> SSOT for creating and organizing GitHub Issues (always active). Lifecycle: `golden-path.md`.
> Label table: `docs/ISSUE_MANAGEMENT.md`.

## 1. Search before you create

```bash
gh issue list --state all --search "<keywords>" --limit 30
```

A match → comment there. Open a new issue only for a genuinely new concern.

## 2. One concern per issue

One issue = one shippable, reviewable concern. Bigger → an **Epic** (Issue Type `Epic`) with
sub-issues: `gh issue edit <child> --parent <epic>`. One-concern governs issues, not PRs.

## 3. Title format

`<type>(<scope>): <subject>` — same types and scopes as the PR title rule in `AGENTS.md`. English
title; Japanese body OK.

## 4. Metadata at creation time

Exactly one `priority:` label, at least one `area:` label, and an Issue Type
(Bug | Feature | Task | Epic). Replace the template's `status:needs-triage`:

```bash
gh issue edit <n> --add-label "priority:P2,area:checks" --remove-label "status:needs-triage" --type Feature
```

Labels come from `.github/labels.yml` (synced by `scripts/sync_labels.sh`). Do not invent names.

## 5. Closing without merge

Duplicate → label `duplicate`, link the canonical issue, close. Won't do → label `wontfix`, say why,
close.

## 6. Promotion bar for follow-up findings

Agents report findings in their final message; the orchestrator decides what becomes an Issue. A
finding is promoted only when (1) a real user of `prescript` can hit it, (2) no existing test or check
already covers it, and (3) it is worth scheduling on its own. At the second instance of the same
defect, file the guard, not the instance. Everything else goes in a comment on the originating PR.

## 7. Body content (an AI files it, another AI implements it)

1. Open with `as-of <SHA>` and one command that reproduces the symptom.
2. Name one thing that is red before the fix and green after it.
3. If the change touches a deliberate behaviour (e.g. `UNRUN` semantics), say what must not break.
4. Evidence is a pasted command and its output. Anything else is a hypothesis.
