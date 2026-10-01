import logging
from cryptography.fernet import Fernet
from backend.app.core.config import settings

logger = logging.getLogger("app.services.encryption")

try:
    # Fernet requires a 32-byte url-safe base64-encoded key.
    # Ex: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    _fernet = Fernet(settings.ENCRYPTION_KEY.encode("utf-8"))
except Exception as e:
    logger.error("Failed to initialize Fernet encryption. Please check that ENCRYPTION_KEY is a valid base64 key.")
    raise ValueError(
        "Invalid ENCRYPTION_KEY config value. Generate a key using: "
        "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
    ) from e

def encrypt_token(plain_text: str) -> str:
    """Encrypts a sensitive credential using symmetric key encryption."""
    if not plain_text:
        return ""
    return _fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_token(encrypted_text: str) -> str:
    """Decrypts an encrypted credential back to its plain-text representation."""
    if not encrypted_text:
        return ""
    return _fernet.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
