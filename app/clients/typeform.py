"""Parse a Typeform `form_response` webhook payload into a Lead.

Typeform gives each field a `ref` you set in the editor, plus a `type`. Refs are the
stable identifier — titles get reworded and break matching. We match on ref first,
then fall back to field type + heuristics so the form works before anyone has set
refs up.

To make matching exact, set these refs on your Typeform fields:
    full_name, email, phone, website, linkedin_url
"""

import logging
import re

from app.models import Lead

log = logging.getLogger(__name__)

# ref (lowercased) -> Lead attribute
REF_MAP = {
    "full_name": "full_name",
    "fullname": "full_name",
    "name": "full_name",
    "email": "email",
    "phone": "phone",
    "phone_number": "phone",
    "website": "website",
    "company_website": "website",
    "linkedin_url": "linkedin_url",
    "linkedin": "linkedin_url",
}

_LINKEDIN_RE = re.compile(r"linkedin\.com/", re.I)


def _answer_value(answer: dict) -> str:
    """Pull the scalar out of a Typeform answer, whatever its type."""
    atype = answer.get("type", "")
    value = answer.get(atype)
    if isinstance(value, dict):  # e.g. choice -> {"label": "..."}
        return str(value.get("label") or value.get("value") or "").strip()
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value or "").strip()


def _normalise_url(value: str) -> str:
    value = value.strip()
    if value and not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value


def parse_form_response(payload: dict) -> Lead:
    form = payload.get("form_response", {})
    answers = form.get("answers", []) or []

    lead = Lead(
        event_id=payload.get("event_id", "") or form.get("token", ""),
        submitted_at=form.get("submitted_at", ""),
    )

    unmatched: list[tuple[str, str]] = []

    for answer in answers:
        field = answer.get("field", {}) or {}
        ref = str(field.get("ref", "")).strip().lower()
        value = _answer_value(answer)
        if not value:
            continue

        attr = REF_MAP.get(ref)
        if attr:
            setattr(lead, attr, value)
        else:
            unmatched.append((answer.get("type", ""), value))

    # Fallback for fields with no recognised ref: infer from the answer's own type.
    for atype, value in unmatched:
        if atype == "email" and not lead.email:
            lead.email = value
        elif atype == "phone_number" and not lead.phone:
            lead.phone = value
        elif atype == "url":
            if _LINKEDIN_RE.search(value) and not lead.linkedin_url:
                lead.linkedin_url = value
            elif not lead.website:
                lead.website = value
        elif atype == "text" and not lead.full_name:
            lead.full_name = value

    # A LinkedIn URL pasted into the website box (and vice versa) is common enough
    # to be worth untangling here rather than sending the wrong URL to the wrong actor.
    site_is_linkedin = bool(_LINKEDIN_RE.search(lead.website))
    li_is_linkedin = bool(_LINKEDIN_RE.search(lead.linkedin_url))

    if site_is_linkedin and not li_is_linkedin:
        # The boxes are swapped (or website holds the LI URL and the LI box is empty).
        lead.website, lead.linkedin_url = lead.linkedin_url, lead.website
    elif site_is_linkedin and li_is_linkedin:
        # Two LinkedIn URLs and no site — keep the one from the LinkedIn field.
        lead.website = ""
    elif lead.linkedin_url and not li_is_linkedin:
        # LinkedIn box holds something that isn't LinkedIn. Salvage it as the website
        # if that's empty, otherwise drop it — a bad URL scrapes worse than none.
        if not lead.website:
            lead.website = lead.linkedin_url
        lead.linkedin_url = ""

    lead.website = _normalise_url(lead.website)
    lead.linkedin_url = _normalise_url(lead.linkedin_url)

    if not lead.is_enrichable():
        log.warning("Lead %s has neither website nor LinkedIn URL", lead.event_id)

    return lead
