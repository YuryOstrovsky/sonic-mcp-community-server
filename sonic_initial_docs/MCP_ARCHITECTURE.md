# MCP Architecture

## Model

MCP Server → SSH → SONiC → CLI Output → JSON Response

## Example Request

{
"tool": "get_interfaces",
"inputs": {
"switch_ip": "10.46.11.50"
}
}

## Execution Flow

1. Receive MCP request
2. Select tool handler
3. SSH into target switch
4. Execute CLI command
5. Return output

## Tool Mapping

| Tool              | Command                |
| ----------------- | ---------------------- |
| get_interfaces    | show interfaces status |
| get_ip_interfaces | show ip interfaces     |
| get_routes        | show ip route          |
| get_system_info   | show version           |

## Design Principle

Treat SONiC as a remote CLI system, not an API-first system.
