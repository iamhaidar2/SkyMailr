import hashlib


def hash_idempotency_key(tenant_id: str, raw_key: str) -> str:
    base = f"{tenant_id}:{raw_key}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()
