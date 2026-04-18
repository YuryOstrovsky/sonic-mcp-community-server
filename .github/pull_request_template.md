<!-- Thanks for contributing! Please fill in the checklist below. -->

## What this PR does


## Why


## Type
- [ ] New tool
- [ ] Bug fix
- [ ] Docs / tests only
- [ ] Refactor (no user-visible change)
- [ ] Other:

## Checklist (new tools only)
- [ ] Handler file at `sonic/tools/<category>/<tool_name>.py` exporting `def <tool_name>(*, inputs, registry, transport, context)`
- [ ] Catalog entry in `generated/mcp_tools.json` with `input_schema`, `policy.risk`, `transport`, description
- [ ] Smoke-tested against a real SONiC switch
- [ ] If MUTATION/DESTRUCTIVE — mutation ledger captures pre/post state
- [ ] `pytest tests/` passes locally (`test_catalog.py` enforces handler↔catalog parity)
- [ ] NL-router pattern added to the client (or explicitly noted as "Tools-view only")
