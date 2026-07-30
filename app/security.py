import base64
import hashlib
import hmac
import logging

log = logging.getLogger(__name__)


def verify_typeform_signature(body: bytes, header: str | None, secret: str) -> bool:
    """Verify Typeform's `Typeform-Signature` header.

    Typeform sends `sha256=<base64(hmac_sha256(secret, raw_body))>`. The MAC is over
    the *raw* bytes, so the caller must pass the unparsed request body — re-serialising
    the JSON changes the bytes and the check fails.
    """
    if not header or not secret:
        return False
    if not header.startswith("sha256="):
        log.warning("Typeform signature header has unexpected prefix")
        return False

    expected = base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")

    return hmac.compare_digest(expected, header[len("sha256=") :])
