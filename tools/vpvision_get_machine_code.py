# -*- coding: utf-8 -*-
"""Print the VP-Vision offline machine code for license binding."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import uuid


def _run_wmic(args: list[str]) -> str:
    try:
        out = subprocess.check_output(
            ["wmic", *args],
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
    except Exception:
        return ""
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return lines[1] if len(lines) >= 2 else ""


def fingerprint_parts() -> dict[str, str]:
    return {
        "machine": platform.machine(),
        "node": platform.node(),
        "platform": platform.platform(),
        "uuid_mac": f"{uuid.getnode():012x}",
        "csproduct_uuid": _run_wmic(["csproduct", "get", "uuid"]),
        "bios_serial": _run_wmic(["bios", "get", "serialnumber"]),
        "baseboard_serial": _run_wmic(["baseboard", "get", "serialnumber"]),
    }


def main() -> None:
    parts = fingerprint_parts()
    stable = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    machine_code = hashlib.sha256(stable.encode("utf-8")).hexdigest().upper()
    print("VP-Vision machine code:")
    print(machine_code)
    print()
    print("Fingerprint parts:")
    print(json.dumps(parts, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
