# Example inventories

The SONiC MCP server uses a static Python inventory at
`sonic/inventory.py`. The examples in this directory show what it
should look like for common topologies — copy the relevant one over
`sonic/inventory.py`, edit the IPs to match your lab, restart.

| File | Topology | Switch count |
|---|---|---|
| `inventory.two-vm.py` | Pair of SONiC VS (the default lab) | 2 |
| `inventory.leaf-spine.py` | 2 spines + 4 leaves, named accordingly | 6 |
| `inventory.single.py` | One switch — smallest working inventory | 1 |

All examples include `tags=(...)` for each device so you can later
filter by role if a tool needs to target only spines or only leaves.
The tags are free-form strings — the runtime doesn't interpret them.
