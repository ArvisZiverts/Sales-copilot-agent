import base64
import hashlib
import hmac
import logging

log = logging.getLogger(__name__)


def _expected(body: bytes, secret: str) -> str:
    return "sha256=" + base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")


def secret_fingerprint(secret: str) -> str:
    """A safe way to compare two copies of a secret across systems.

    Logs the length and a short hash. Two systems showing the same fingerprint hold
    the same string; different fingerprints mean a bad paste. Never logs the secret.
    """
    if not secret:
        return "len=0 <EMPTY>"
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]
    return f"len={len(secret)} sha256:{digest}"


def verify_typeform_signature(body: bytes, header: str | None, secret: str) -> bool:
    """Verify Typeform's `Typeform-Signature` header.

    Typeform sends `sha256=<base64(hmac_sha256(secret, raw_body))>`. The MAC is over
    the *raw* bytes, so the caller must pass the unparsed request body — re-serialising
    the JSON changes the bytes and the check fails.

    On failure this logs enough to tell the three causes apart (no header, wrong
    secret, mangled body) without ever logging the secret itself.
    """
    if not secret:
        log.warning("SIGNATURE FAIL: no TYPEFORM_WEBHOOK_SECRET configured on this server")
        return False

    if not header:
        log.warning(
            "SIGNATURE FAIL: request carried no Typeform-Signature header. "
            "Typeform sends one only when a Secret is set on the webhook. "
            "server_secret=%s body_len=%d",
            secret_fingerprint(secret), len(body),
        )
        return False

    if not header.startswith("sha256="):
        log.warning("SIGNATURE FAIL: unexpected header format %r", header[:40])
        return False

    expected = _expected(body, secret)
    if hmac.compare_digest(expected, header):
        return True

    log.warning(
        "SIGNATURE FAIL: mismatch. received=%s computed=%s body_len=%d server_secret=%s "
        "-- same body_len with different digests means the secret in Typeform differs "
        "from the one on this server",
        header, expected, len(body), secret_fingerprint(secret),
    )
    return False
