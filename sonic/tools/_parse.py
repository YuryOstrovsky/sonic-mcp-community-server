"""Shared CLI output parsers for SONiC `show` commands.

Two formats in common use:
  1. Tabulate box-drawing (e.g. `show vlan brief`):
         +-----------+--------------+---------+
         | VLAN ID   | IP Address   | Ports   |
         +===========+==============+=========+
         | 100       | 10.1.1.1/24  | Eth0... |
         +-----------+--------------+---------+

  2. Fixed-width with dashed separator (e.g. `show arp`):
         Address     MacAddress         Iface
         ----------  -----------------  -------
         10.46.11.8  0e:29:db:0f:4f:be  eth0

Both return a list of dicts keyed by header text (normalized: lowercase,
spaces/punctuation replaced with underscores).
"""

from __future__ import annotations

import re
from typing import Dict, List


def _normalize_key(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def parse_box_table(text: str) -> List[Dict[str, str]]:
    """Parse tabulate box-drawing output. Returns empty list if no rows."""
    if not text:
        return []
    lines = text.splitlines()

    # Find header row: first line that starts with "|" and contains at least two "|"
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.startswith("|") and ln.count("|") >= 2:
            header_idx = i
            break
    if header_idx is None:
        return []

    headers = [c.strip() for c in lines[header_idx].split("|")[1:-1]]
    keys = [_normalize_key(h) for h in headers]

    rows: List[Dict[str, str]] = []
    for ln in lines[header_idx + 1:]:
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")[1:-1]]
        if len(cells) != len(keys):
            continue
        rows.append(dict(zip(keys, cells)))
    return rows


def parse_fixed_width_table(
    text: str,
    stop_markers: List[str] = ("Total number", "Total entries"),
) -> List[Dict[str, str]]:
    """Parse fixed-width tables with a dashed separator line below the header.

    Column widths are inferred from the dash runs. Stops at any line beginning
    with one of `stop_markers` (e.g., "Total number of entries 1").
    """
    if not text:
        return []
    lines = text.splitlines()

    # Find the dashed separator line (the line made of dashes and spaces).
    sep_idx = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped and set(stripped) <= {"-", " "}:
            sep_idx = i
            break
    if sep_idx is None or sep_idx == 0:
        return []

    header_line = lines[sep_idx - 1]
    sep_line = lines[sep_idx]

    # Build column slices from dash runs in the separator line.
    spans: List[tuple] = []
    i = 0
    while i < len(sep_line):
        if sep_line[i] == "-":
            j = i
            while j < len(sep_line) and sep_line[j] == "-":
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    if not spans:
        return []

    keys = [_normalize_key(header_line[s:e]) for s, e in spans]

    rows: List[Dict[str, str]] = []
    for ln in lines[sep_idx + 1:]:
        if not ln.strip():
            continue
        if any(ln.strip().startswith(m) for m in stop_markers):
            break
        # For the last column, read to end of line to accommodate trailing values
        cells: List[str] = []
        for idx, (s, e) in enumerate(spans):
            if idx == len(spans) - 1:
                cells.append(ln[s:].strip())
            else:
                cells.append(ln[s:e].strip())
        if len(cells) == len(keys):
            rows.append(dict(zip(keys, cells)))
    return rows


def parse_kv_lines(text: str, sep: str = ":") -> Dict[str, str]:
    """Parse `Key: Value` lines into a flat dict. Blank lines and separators ignored."""
    out: Dict[str, str] = {}
    for ln in (text or "").splitlines():
        if sep not in ln:
            continue
        k, v = ln.split(sep, 1)
        k, v = k.strip(), v.strip()
        if not k or "---" in k:
            continue
        out[_normalize_key(k)] = v
    return out
