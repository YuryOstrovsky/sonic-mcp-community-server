# SONiC MCP Server (Lab + Integration Guide)

## Overview

This project provides a Model Context Protocol (MCP) server for interacting with SONiC switches via SSH.

The lab environment consists of two SONiC virtual switches running on KVM, reachable over a management network.

## Quick Start

1. Review lab details in `docs/LAB_SETUP.md`
2. Use credentials in `docs/ACCESS.md`
3. Start implementing tools using commands in `docs/COMMANDS.md`
4. Follow architecture in `docs/MCP_ARCHITECTURE.md`

## Goal

Enable AI-driven interaction with SONiC devices via MCP tools such as:

* get_interfaces
* get_ip_interfaces
* get_routes
* get_system_info

## Important Notes

* LLDP is not reliable in SONiC VS
* Use SSH for all interactions
* Start with raw CLI output, then evolve to structured parsing


## LLDP / Topology Note

SONiC VS has limited support for LLDP neighbor discovery.

A separate Containerlab-based Linux lab is available for:

* LLDP testing
* topology discovery

See: docs/LLDP_TOPOLOGY.md

This is optional and not required for initial MCP development.
