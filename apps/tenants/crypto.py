import hashlib
import hmac
import secrets
import string

from django.conf import settings


def generate_api_key(prefix: str = "sk_live_") -> str:
    alphabet = string.ascii_letters + string.digits
    tail = "".join(secrets.choice(alphabet) for _ in range(40))
    return f"{prefix}{tail}"


def hash_api_key(raw_key: str) -> str:
    pepper = (getattr(settings, "API_KEY_PEPPER", None) or settings.SECRET_KEY).encode()
    return hmac.new(pepper, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(raw_key), stored_hash)
