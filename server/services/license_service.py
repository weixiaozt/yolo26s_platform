# -*- coding: utf-8 -*-
"""Offline machine-bound license checks for controlled deployments."""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..config import settings


PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAnKe/a+SB3JMImLGn/zCPwLFXH++lTiCAkyASuym9HcE=
-----END PUBLIC KEY-----
"""


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


def machine_fingerprint_parts() -> dict[str, str]:
    """Return stable local identifiers used to derive the offline machine code."""
    return {
        "machine": platform.machine(),
        "node": platform.node(),
        "platform": platform.platform(),
        "uuid_mac": f"{uuid.getnode():012x}",
        "csproduct_uuid": _run_wmic(["csproduct", "get", "uuid"]),
        "bios_serial": _run_wmic(["bios", "get", "serialnumber"]),
        "baseboard_serial": _run_wmic(["baseboard", "get", "serialnumber"]),
    }


def get_machine_code() -> str:
    parts = machine_fingerprint_parts()
    stable = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest().upper()


def _license_path() -> Path:
    path = Path(settings.VPVISION_LICENSE_FILE)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _canonical_payload(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_license_file(path: Path | None = None) -> dict:
    path = path or _license_path()
    if not path.exists():
        raise RuntimeError(f"license file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    payload = data.get("payload")
    signature_b64 = data.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature_b64, str):
        raise RuntimeError("invalid license format")

    public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
    if not isinstance(public_key, Ed25519PublicKey):
        raise RuntimeError("invalid public key")

    try:
        public_key.verify(base64.b64decode(signature_b64), _canonical_payload(payload))
    except (InvalidSignature, ValueError) as exc:
        raise RuntimeError("invalid license signature") from exc

    expected_code = str(payload.get("machine_code", "")).upper()
    actual_code = get_machine_code()
    if expected_code != actual_code:
        raise RuntimeError("license is not valid for this machine")

    expires_at = payload.get("expires_at")
    if expires_at:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expiry:
            raise RuntimeError("license has expired")

    return payload


def enforce_license_if_required() -> None:
    if not settings.VPVISION_LICENSE_REQUIRED:
        return
    payload = verify_license_file()
    customer = payload.get("customer") or "licensed customer"
    print(f"[license] OK: {customer}, machine={payload.get('machine_code')}")
