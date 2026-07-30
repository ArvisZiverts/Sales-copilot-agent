import base64
import hashlib
import hmac

from app.security import verify_typeform_signature

SECRET = "test-secret"
BODY = b'{"event_id":"1"}'


def sign(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return "sha256=" + base64.b64encode(digest).decode()


def test_valid_signature_passes():
    assert verify_typeform_signature(BODY, sign(BODY), SECRET)


def test_wrong_secret_fails():
    assert not verify_typeform_signature(BODY, sign(BODY, "other-secret"), SECRET)


def test_tampered_body_fails():
    assert not verify_typeform_signature(b'{"event_id":"2"}', sign(BODY), SECRET)


def test_missing_header_fails():
    assert not verify_typeform_signature(BODY, None, SECRET)


def test_malformed_header_fails():
    assert not verify_typeform_signature(BODY, "notsha256=abc", SECRET)


def test_empty_secret_fails_closed():
    assert not verify_typeform_signature(BODY, sign(BODY), "")
