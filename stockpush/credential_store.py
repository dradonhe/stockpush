"""
stockpush.credential_store

使用对称加密（Fernet）对 Telegram 凭据进行加密/解密。

算法：Fernet（对称，基于 AES + HMAC），在 `webstock/config/telegram_credentials.key` 存放密钥。

注意：密钥保存在服务端文件系统中，客户端保存的是加密后的字符串，发送时由服务端解密后使用。
"""
import os
from pathlib import Path
from typing import Tuple, Dict

from cryptography.fernet import Fernet


KEY_FILE = Path(__file__).resolve().parent.parent / 'config' / 'telegram_credentials.key'


def _ensure_key() -> bytes:
    """确保密钥存在，存在则读取，不存在则生成并写入文件。返回原始 key bytes。"""
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        # 写入密钥文件
        with open(KEY_FILE, 'wb') as f:
            f.write(key)
        try:
            os.chmod(KEY_FILE, 0o600)
        except Exception:
            # Windows 上可能无效，忽略
            pass
        return key

    with open(KEY_FILE, 'rb') as f:
        return f.read()


def encrypt_value(plaintext: str) -> str:
    key = _ensure_key()
    f = Fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(token: str) -> str:
    key = _ensure_key()
    f = Fernet(key)
    return f.decrypt(token.encode()).decode()


def encrypt_credentials(bot_token: str, chat_id: str) -> Dict[str, str]:
    return {
        'enc_bot_token': encrypt_value(bot_token),
        'enc_chat_id': encrypt_value(chat_id),
        'algo': 'Fernet'
    }


def decrypt_credentials(enc_bot_token: str, enc_chat_id: str) -> Tuple[str, str]:
    return decrypt_value(enc_bot_token), decrypt_value(enc_chat_id)
