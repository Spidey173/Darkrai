import hashlib
import hmac
import logging

logger = logging.getLogger("app.utils.signature")

def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Verifies HMAC-SHA256 signature of incoming webhooks from GitHub in constant time."""
    if not signature_header or not secret:
        logger.warning("Signature header or webhook secret is empty.")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("Signature header is not in the expected format (sha256=...).")
        return False

    # Extract raw hex token from signature string
    received_signature = signature_header.split("sha256=")[-1].strip()
    
    # Generate signature using the local secret key
    computed_signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()

    # constant time check to mitigate timing attacks
    return hmac.compare_digest(received_signature, computed_signature)
