"""Shared credential utility functions used across services and workers."""


def decrypt_config_value(raw_value: str) -> str:
    """Try to decrypt a config value. Falls back to raw value if decryption fails."""
    if not raw_value:
        return ""
    try:
        from stockpush.credential_store import decrypt_value
        return decrypt_value(raw_value)
    except Exception:
        return raw_value
