# systemd service — SONiC MCP Community Server

This directory ships a systemd unit so the MCP server runs on boot and can
be managed with `systemctl start/stop/restart/status`.

## Install

Run once as root (sudo password will be prompted):

```bash
cd /home/user01/sonic-mcp-community-server

sudo cp systemd/sonic-mcp.service /etc/systemd/system/sonic-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now sonic-mcp
```

`enable --now` both (a) marks it to auto-start at boot and (b) starts it
immediately.

## Verify

```bash
systemctl status sonic-mcp --no-pager
journalctl -u sonic-mcp -f          # follow logs
curl -sS http://127.0.0.1:8000/health | jq
curl -sS http://127.0.0.1:8000/ready  | jq
```

## Day-to-day operations

```bash
sudo systemctl restart sonic-mcp    # after editing .env or code
sudo systemctl stop sonic-mcp
sudo systemctl start sonic-mcp
sudo systemctl disable sonic-mcp    # stop auto-start at boot (keeps the service file)
```

## Uninstall

```bash
sudo systemctl disable --now sonic-mcp
sudo rm /etc/systemd/system/sonic-mcp.service
sudo systemctl daemon-reload
```

## Paths baked into the unit

- WorkingDirectory: `/home/user01/sonic-mcp-community-server`
- Python:          `/home/user01/sonic-mcp-community-server/.venv/bin/python`
- EnvironmentFile: `/home/user01/sonic-mcp-community-server/.env`
- Writable path:   `/home/user01/sonic-mcp-community-server/logs`
- User / Group:    `user01`

If you move the repo or change the user, edit `systemd/sonic-mcp.service`
and re-copy to `/etc/systemd/system/`.

## Security notes

The unit applies basic hardening (`NoNewPrivileges`, `PrivateTmp`,
`ProtectSystem=full`, `ProtectHome=read-only`, `ReadWritePaths=…/logs`).
The process still has network access (required — it connects to SONiC
switches over SSH/HTTPS) and can read everything in its working
directory (required — it loads `generated/mcp_tools.json` and `.env`).
