## Linked Issue

Closes #<!-- issue number -->

## Summary

<!-- What changed and why. Japanese OK. -->

## Verification

```
<!-- paste: uv run keel verify examples/gb200-1su/netlist.yaml | grep -E '^PASS' (summary line), before and after -->
```

## Checklist

- [ ] Title follows `<type>(<scope>): <subject> #<issue>`
- [ ] Tests cover every changed behaviour (PASS / FAIL / UNRUN for a new check)
- [ ] Docs updated in this PR if behaviour changed (`doc-update.md`)
- [ ] Only public data under `examples/` (`public-data.md`)
- [ ] CI green
