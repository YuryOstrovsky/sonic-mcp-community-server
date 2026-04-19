"""Tool: validate_fabric_vs_intent

Compare the live fabric against a declarative JSON intent file and report
drift. This is a poor-man's "controller"-style audit — no SoT, no Git,
just a static JSON you hand-maintain or generate.

Path resolution order:
  1. `inputs.intent_path` (explicit per-invocation override)
  2. $SONIC_FABRIC_INTENT_PATH env var (useful in containerised runs where
     the operator bind-mounts an intent file from the host)
  3. config/fabric_intent.json relative to the server working directory

The env-var knob is the key to decoupling intent ownership from the
container image: operators can ship one MCP image and point it at any
fabric-specific intent file on the host.

Intent file shape (all fields optional at both levels):
{
  "switches": {
    "10.46.11.50": {
      "asn": 65001,
      "hostname": "vm1",
      "hwsku": "Force10-S6000",
      "expected_bgp_peers": [
        {"peer_ip": "192.168.1.2", "remote_asn": 65100}
      ],
      "expected_interfaces": [
        {"name": "Ethernet0", "address": "192.168.1.1/30", "mtu": 9100}
      ]
    }
  }
}

Output lists per-switch drift items, plus a summary.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from sonic.tools._fanout import fan_out
from sonic.tools.interfaces.get_ip_interfaces import get_ip_interfaces
from sonic.tools.interfaces.get_interfaces import get_interfaces
from sonic.tools.routing.get_bgp_summary import get_bgp_summary


_ENV_INTENT_PATH = "SONIC_FABRIC_INTENT_PATH"
_DEFAULT_INTENT_RELATIVE = Path("config") / "fabric_intent.json"


def _resolve_default_path() -> Path:
    """Precedence: explicit caller arg > env var > config/fabric_intent.json."""
    from sonic.inventory import _validated_config_path
    return _validated_config_path(os.environ.get(_ENV_INTENT_PATH), _DEFAULT_INTENT_RELATIVE)


def _load_intent(explicit: Optional[str]) -> Optional[Dict[str, Any]]:
    path = Path(explicit) if explicit else _resolve_default_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"could not parse intent file {path}: {e}")


def _fanout(handler, *, inventory, transport, registry, context, switch_ips):
    return fan_out(
        handler=handler, inventory=inventory, transport=transport,
        registry=registry, inputs={}, context=context or {}, switch_ips=switch_ips,
    )


def _peers_observed(bgp_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for p in (bgp_payload or {}).get("ipv4", {}).get("peers") or []:
        ip = p.get("peer")
        if ip:
            out[ip] = {"remote_as": p.get("remote_as"), "established": bool(p.get("established"))}
    return out


def _ifaces_observed_ips(ipi_payload: Dict[str, Any]) -> Dict[str, List[str]]:
    """{interface_name: [ipv4 CIDR, ...]}."""
    out: Dict[str, List[str]] = {}
    for row in (ipi_payload or {}).get("ip_interfaces") or []:
        if row.get("family") != "ipv4":
            continue
        name = row.get("interface")
        addr = row.get("address")
        if name and addr:
            out.setdefault(name, []).append(addr)
    return out


def _ifaces_observed_mtu(iface_payload: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in (iface_payload or {}).get("interfaces") or []:
        name = row.get("name")
        mtu = row.get("mtu")
        if name and mtu is not None:
            try:
                out[name] = int(mtu)
            except (TypeError, ValueError):
                pass
    return out


def _asn_observed(bgp_payload: Dict[str, Any]) -> Optional[int]:
    # get_bgp_summary puts the local ASN on the `ipv4.as` key (matching FRR's
    # summary output); older callers sometimes set `local_as` too — accept
    # either so this stays compatible if the read tool evolves.
    ipv4 = (bgp_payload or {}).get("ipv4") or {}
    a = ipv4.get("as") or ipv4.get("local_as")
    try:
        return int(a) if a is not None else None
    except (TypeError, ValueError):
        return None


def validate_fabric_vs_intent(
    *,
    inputs: Dict[str, Any],
    registry,
    transport,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    intent = _load_intent(inputs.get("intent_path"))
    if intent is None:
        return {
            "summary": {
                "intent_loaded": False,
                "intent_path": str(Path(inputs.get("intent_path") or _resolve_default_path())),
                "drift_count": 0,
                "source": "fabric intent validator",
                "note": (
                    "no intent file found — create one at "
                    f"{_resolve_default_path()} to start auditing against "
                    f"expected state. (override this path via the "
                    f"{_ENV_INTENT_PATH} env var or the `intent_path` input.)"
                ),
            },
            "switches": [],
            "example_intent": _example_intent(),
        }

    intent_switches: Dict[str, Any] = intent.get("switches") or {}
    scope = list(intent_switches.keys()) or list(transport.inventory.all_ips())

    bgp   = _fanout(get_bgp_summary,    inventory=transport.inventory, transport=transport, registry=registry, context=context, switch_ips=scope)
    ipifs = _fanout(get_ip_interfaces,  inventory=transport.inventory, transport=transport, registry=registry, context=context, switch_ips=scope)
    ifs   = _fanout(get_interfaces,     inventory=transport.inventory, transport=transport, registry=registry, context=context, switch_ips=scope)

    per_switch: List[Dict[str, Any]] = []
    total_drift = 0

    for ip, expected in intent_switches.items():
        drift: List[Dict[str, str]] = []
        bgp_entry = (bgp.get("by_switch") or {}).get(ip) or {}
        ipi_entry = (ipifs.get("by_switch") or {}).get(ip) or {}
        if_entry  = (ifs.get("by_switch")   or {}).get(ip) or {}

        bgp_payload = bgp_entry.get("payload") if bgp_entry.get("status") == "ok" else {}
        ipi_payload = ipi_entry.get("payload") if ipi_entry.get("status") == "ok" else {}
        if_payload  = if_entry.get("payload")  if if_entry.get("status")  == "ok" else {}

        # ASN check
        exp_asn = expected.get("asn")
        obs_asn = _asn_observed(bgp_payload or {})
        if exp_asn is not None and obs_asn is not None and int(exp_asn) != obs_asn:
            drift.append({"kind": "asn",
                          "expected": str(exp_asn),
                          "observed": str(obs_asn),
                          "detail": "local ASN differs from intent"})

        # BGP peers check
        exp_peers = {p.get("peer_ip"): p.get("remote_asn") for p in expected.get("expected_bgp_peers") or []}
        obs_peers = _peers_observed(bgp_payload or {})
        for peer, exp_ras in exp_peers.items():
            if peer not in obs_peers:
                drift.append({"kind": "bgp_peer_missing",
                              "expected": peer,
                              "observed": "absent",
                              "detail": f"intent expects peer {peer} — not configured"})
            elif exp_ras is not None and int(exp_ras) != int(obs_peers[peer].get("remote_as") or 0):
                drift.append({"kind": "bgp_peer_remote_as",
                              "expected": f"{peer} remote-as {exp_ras}",
                              "observed": f"{peer} remote-as {obs_peers[peer].get('remote_as')}",
                              "detail": "remote-as differs from intent"})
        for peer in obs_peers:
            if peer not in exp_peers:
                drift.append({"kind": "bgp_peer_unexpected",
                              "expected": "absent",
                              "observed": peer,
                              "detail": "peer is configured but not in intent"})

        # Interface checks
        obs_ipifs = _ifaces_observed_ips(ipi_payload or {})
        obs_mtu   = _ifaces_observed_mtu(if_payload  or {})
        for exp_if in expected.get("expected_interfaces") or []:
            name = exp_if.get("name")
            if not name:
                continue
            exp_addr = exp_if.get("address")
            exp_mtu  = exp_if.get("mtu")
            if exp_addr:
                if exp_addr not in (obs_ipifs.get(name) or []):
                    drift.append({"kind": "iface_address",
                                  "expected": f"{name} {exp_addr}",
                                  "observed": f"{name} {obs_ipifs.get(name) or '—'}",
                                  "detail": "IP assignment differs from intent"})
            if exp_mtu is not None and name in obs_mtu and int(exp_mtu) != obs_mtu[name]:
                drift.append({"kind": "iface_mtu",
                              "expected": f"{name} mtu {exp_mtu}",
                              "observed": f"{name} mtu {obs_mtu[name]}",
                              "detail": "MTU differs from intent"})

        total_drift += len(drift)
        per_switch.append({
            "switch_ip": ip,
            "intent_hostname": expected.get("hostname"),
            "reachable": bgp_entry.get("status") == "ok",
            "drift_count": len(drift),
            "drift": drift,
        })

    return {
        "summary": {
            "intent_loaded": True,
            "intent_path": str(Path(inputs.get("intent_path") or _resolve_default_path())),
            "switch_count": len(per_switch),
            "drift_count": total_drift,
            "compliant": total_drift == 0,
            "source": "fabric intent validator",
        },
        "switches": per_switch,
    }


def _example_intent() -> Dict[str, Any]:
    return {
        "switches": {
            "10.46.11.50": {
                "asn": 65001,
                "hostname": "vm1",
                "expected_bgp_peers": [
                    {"peer_ip": "192.168.1.2", "remote_asn": 65100}
                ],
                "expected_interfaces": [
                    {"name": "Ethernet0", "address": "192.168.1.1/30", "mtu": 9100}
                ],
            }
        }
    }
