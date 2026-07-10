# -*- coding: utf-8 -*-
"""Create a signed VP-Vision offline license.

The private key must stay on the administrator machine and must not be copied
into customer deployment packages.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _canonical_payload(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create VP-Vision offline license.dat")
    parser.add_argument("--machine-code", required=True, help="Machine code from vpvision_get_machine_code.py")
    parser.add_argument("--customer", default="offline-customer", help="Customer or machine label")
    parser.add_argument("--expires-at", default="", help="Optional ISO time, e.g. 2027-12-31T23:59:59+08:00")
    parser.add_argument("--out", default="license.dat", help="Output license path")
    parser.add_argument(
        "--private-key",
        default=os.environ.get(
            "VPVISION_PRIVATE_KEY_FILE",
            str(Path(__file__).resolve().parent.parent / "admin_private" / "vpvision_license_private_key.pem"),
        ),
        help="Ed25519 private key PEM path",
    )
    args = parser.parse_args()

    private_key_path = Path(args.private_key)
    private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SystemExit("private key is not Ed25519")

    payload = {
        "product": "VP-Vision",
        "machine_code": args.machine_code.strip().upper(),
        "customer": args.customer,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    if args.expires_at:
        payload["expires_at"] = args.expires_at

    signature = private_key.sign(_canonical_payload(payload))
    license_data = {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }

    out = Path(args.out)
    out.write_text(json.dumps(license_data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"OK: {out.resolve()}")


if __name__ == "__main__":
    main()
