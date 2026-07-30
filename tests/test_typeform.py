import json
from pathlib import Path

from app.clients.typeform import parse_form_response

FIXTURE = Path(__file__).parent / "fixtures" / "typeform_payload.json"


def load():
    return json.loads(FIXTURE.read_text())


def test_parses_all_fields():
    lead = parse_form_response(load())
    assert lead.event_id == "01JTEST0000000000000000001"
    assert lead.full_name == "Dana Whitfield"
    assert lead.email == "dana@northgateops.com"
    assert lead.phone == "+15551234567"
    assert lead.website == "https://northgateops.com"
    assert lead.linkedin_url == "https://www.linkedin.com/in/danawhitfield/"
    assert lead.is_enrichable()


def test_bare_domain_gets_scheme():
    payload = load()
    payload["form_response"]["answers"][3]["url"] = "acme.io"
    assert parse_form_response(payload).website == "https://acme.io"


def test_swapped_urls_are_untangled():
    """Leads routinely paste their LinkedIn into the website box."""
    payload = load()
    payload["form_response"]["answers"][3]["url"] = "https://linkedin.com/in/someone"
    payload["form_response"]["answers"][4]["url"] = "https://realcompany.com"

    lead = parse_form_response(payload)
    assert lead.linkedin_url == "https://linkedin.com/in/someone"
    assert lead.website == "https://realcompany.com"


def test_unrecognised_refs_fall_back_to_answer_type():
    payload = load()
    for answer in payload["form_response"]["answers"]:
        answer["field"]["ref"] = "some_random_ref_id"

    lead = parse_form_response(payload)
    assert lead.email == "dana@northgateops.com"
    assert lead.phone == "+15551234567"
    assert lead.linkedin_url == "https://www.linkedin.com/in/danawhitfield/"
    assert lead.website == "https://northgateops.com"


def test_missing_urls_marks_lead_unenrichable():
    payload = load()
    payload["form_response"]["answers"] = payload["form_response"]["answers"][:3]
    lead = parse_form_response(payload)
    assert not lead.is_enrichable()
