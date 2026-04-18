# Future Hardware Capabilities (RoCE / RDMA)

## Overview

The lab environment may include servers equipped with RDMA-capable NICs (e.g., Mellanox ConnectX series).

These NICs support:

* RoCEv2 (RDMA over Converged Ethernet)
* high-performance, low-latency networking

---

## Current Status

RoCE functionality is NOT part of the current MCP development scope.

The current lab:

* uses SONiC VS (virtual switches)
* does not provide real RDMA dataplane behavior

---

## Future Opportunities

The MCP server may later support:

* QoS inspection (PFC, ECN)
* RDMA interface discovery
* fabric validation for RoCE workloads

Example future tools:

* get_qos_config
* check_pfc_status
* validate_roce_fabric

---

## Recommendation

Do NOT include RoCE logic in initial MCP implementation.

Focus on:

* CLI execution
* device state
* basic automation

RoCE support can be added in later phases when real hardware dataplane is introduced.

