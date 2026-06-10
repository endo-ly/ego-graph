"""OAuth token encryption."""

from cryptography.fernet import Fernet, InvalidToken


class TokenDecryptionError(ValueError):
    """暗号鍵の不一致などにより token を復号できない。"""


class TokenCipher:
    """Fernet により token を暗号化・復号する。"""

    def __init__(self, encryption_key: str) -> None:
        try:
            self._fernet = Fernet(encryption_key.encode())
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "invalid_google_health_token_encryption_key: "
                "a URL-safe base64-encoded 32-byte Fernet key is required"
            ) from exc

    def encrypt(self, value: str) -> bytes:
        """平文を暗号化する。"""
        return self._fernet.encrypt(value.encode())

    def decrypt(self, value: bytes) -> str:
        """暗号文を復号する。"""
        try:
            return self._fernet.decrypt(value).decode()
        except InvalidToken as exc:
            raise TokenDecryptionError("google_health_token_decryption_failed") from exc
