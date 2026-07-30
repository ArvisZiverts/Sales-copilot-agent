"""POST the test fixture at a locally running server, correctly signed.

    uvicorn app.main:app --reload          # in one terminal
    python -m scripts.smoke_local_webhook  # in another

Exercises the real signature path, so it also proves your TYPEFORM_WEBHOOK_SECRET
plumbing works before you point Typeform at anything.

The fixture's URLs are fake, which exercises the failure path. To drive a full
enrichment instead, pass real ones:

    python -m scripts.smoke_local_webhook --website https://acme.com \\
        --linkedin https://www.linkedin.com/in/someone/
"""

import argparse
import base64
import hashlib
import hmac
import json
import uuid
from pathlib import Path

import httpx

from app.config import get_settings

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "typeform_payload.json"


def _set_answer(payload: dict, ref: str, value: str) -> None:
    for answer in payload["form_response"]["answers"]:
        if answer.get("field", {}).get("ref") == ref:
            answer[answer["type"]] = value
            return
    raise SystemExit(f"fixture has no field with ref={ref!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhook/typeform")
    parser.add_argument("--website")
    parser.add_argument("--linkedin")
    parser.add_argument("--name")
    args = parser.parse_args()

    payload = json.loads(FIXTURE.read_text())
    # Fresh event_id each run, or the idempotency cache rejects the second attempt.
    payload["event_id"] = f"smoke_{uuid.uuid4().hex[:12]}"

    if args.website:
        _set_answer(payload, "website", args.website)
    if args.linkedin:
        _set_answer(payload, "linkedin_url", args.linkedin)
    if args.name:
        _set_answer(payload, "full_name", args.name)

    body = json.dumps(payload).encode()
    secret = get_settings().typeform_webhook_secret
    signature = "sha256=" + base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()

    response = httpx.post(
        args.url,
        content=body,
        headers={"Content-Type": "application/json", "Typeform-Signature": signature},
        timeout=30,
    )
    print(response.status_code, response.text)
    print("\nWatch the server logs — enrichment runs in the background and takes 60-150s.")


if __name__ == "__main__":
    main()
