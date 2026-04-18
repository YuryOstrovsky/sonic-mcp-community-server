# LLDP & Topology Lab (Supplementary Environment)

## Purpose

This lab provides working LLDP-based topology discovery, which is NOT fully functional in SONiC VS.

It is intended for:

* topology discovery testing
* graph building
* MCP "get_neighbors" style tools

It is NOT required for core MCP functionality.

---

## Why This Exists

SONiC VS (virtual switch) has limitations:

* LLDP RX is unreliable or disabled
* Neighbor discovery may not work correctly

Therefore, a separate Linux-based lab was created.

---

## LLDP Lab Architecture

Containerlab-based topology:

sw1 (Linux container)
│
│ eth1
│
└────── sw2 (Linux container)

---

## Access

Enter nodes:

docker exec -it clab-lldp-lab-sw1 bash
docker exec -it clab-lldp-lab-sw2 bash

---

## Start LLDP

Run on BOTH nodes:

lldpd -d

---

## Verify Neighbors

lldpcli show neighbors

---

## Example Output

Interface: eth1
SysName: sw2

---

## Key Interfaces

| Interface | Purpose                           |
| --------- | --------------------------------- |
| eth0      | management network                |
| eth1      | inter-node link (actual topology) |

---

## How MCP Can Use This

Example tool:

get_neighbors

Implementation:

lldpcli show neighbors

---

## Integration Strategy

Two possible approaches:

### Option A (Simple)

Use LLDP lab as topology source only

### Option B (Advanced)

Map LLDP nodes to SONiC devices via IP or naming convention

---

## Important Notes

* This lab is OPTIONAL
* Core MCP functionality does NOT depend on it
* Use it only when topology awareness is required

---

## Recommendation

Start MCP development using SONiC VMs only.

Add LLDP integration later if needed.
