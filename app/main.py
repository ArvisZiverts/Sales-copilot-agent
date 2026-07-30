import logging
from collections import OrderedDict

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from app.clients.typeform import parse_form_response
from app.config import get_settings
from app.pipeline import process_lead
from app.security import verify_typeform_signature

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("sales-copilot")

app = FastAPI(title="Sales Copilot", version="1.0.0")

# Typeform retries on any non-2xx, and occasionally redelivers a 2xx event. Keyed on
# event_id so a redelivery doesn't produce a second sheet row and a second Apify bill.
# In-memory: fine for a single Railway replica. If we scale to >1, move this to Redis
# or the sheet itself — otherwise each replica has its own blind spot.
_SEEN_EVENTS: OrderedDict[str, None] = OrderedDict()
_MAX_SEEN = 1000


def _already_processed(event_id: str) -> bool:
    if not event_id:
        return False
    if event_id in _SEEN_EVENTS:
        return True
    _SEEN_EVENTS[event_id] = None
    while len(_SEEN_EVENTS) > _MAX_SEEN:
        _SEEN_EVENTS.popitem(last=False)
    return False


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/typeform")
async def typeform_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    typeform_signature: str | None = Header(default=None, alias="Typeform-Signature"),
):
    settings = get_settings()
    body = await request.body()

    if settings.allow_unsigned_webhooks:
        log.warning("Signature verification is DISABLED — local testing only")
    elif not verify_typeform_signature(body, typeform_signature, settings.typeform_webhook_secret):
        log.warning("Rejected webhook with bad or missing signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body is not valid JSON")

    lead = parse_form_response(payload)

    if _already_processed(lead.event_id):
        log.info("Duplicate delivery of %s — ignoring", lead.event_id)
        return {"status": "duplicate_ignored"}

    # Ack now, work later. Typeform's timeout is 10s; enrichment takes 40-90s.
    background_tasks.add_task(process_lead, lead)
    log.info("Accepted lead %s, queued for enrichment", lead.event_id)

    return {"status": "accepted", "event_id": lead.event_id}
