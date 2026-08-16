import hashlib
import json
from typing import Any


def payload_hash(payload: Any) -> str:
    """Stable content hash used to detect unchanged vendor payloads."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
