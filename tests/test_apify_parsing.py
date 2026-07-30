"""Parsing tests for Apify output — no network.

The field names here were verified against live actor output on 2026-07-30. If an
actor changes its schema these tests keep passing while production silently degrades,
so `scripts/smoke_apify.py` remains the real check. What these lock in is the
flattening logic: nested dicts must never leak into the model's context.
"""

from app.clients.apify import _clean_markdown, _flatten_linkedin, _plain

# Trimmed from real harvestapi/linkedin-profile-scraper output.
PROFILE = {
    "firstName": "Bill",
    "lastName": "Gates",
    "headline": "Chair, Gates Foundation and Founder, Breakthrough Energy",
    "location": {
        "linkedinText": "Seattle, Washington, United States",
        "countryCode": "US",
        "parsed": {"text": "Seattle, WA, United States"},
    },
    "about": "Chair of the Gates Foundation.",
    "followerCount": 40549518,
    "connectionsCount": 8,
    "hiring": False,
    "openToWork": False,
    "influencer": True,
    "creator": True,
    "websites": ["https://gatesnot.es/tgn"],
    "currentPosition": [{"position": "Co-chair", "companyName": "Gates Foundation"}],
    "experience": [
        {"position": "Co-chair", "companyName": "Gates Foundation", "duration": "26 yrs 7 mos"},
        {"position": "Founder", "companyName": "Breakthrough Energy", "duration": "11 yrs 7 mos"},
    ],
    "education": [{"schoolName": "Harvard University"}, {"schoolName": "Lakeside School"}],
    "skills": [],
    # Large, useless-to-us keys the flattener must ignore rather than dump into context.
    "moreProfiles": [{"firstName": "Sundar"}] * 20,
    "interests": [{"interestName": "Top Voices"}],
}


def test_name_is_assembled_from_first_and_last():
    """There is no `fullName` field — assuming one produced a blank Name line."""
    assert "Name: Bill Gates" in _flatten_linkedin(PROFILE)


def test_nested_location_is_flattened_not_dumped():
    out = _flatten_linkedin(PROFILE)
    assert "Location: Seattle, Washington, United States" in out
    assert "linkedinText" not in out
    assert "countryCode" not in out


def test_uses_followers_not_connections():
    """connectionsCount saturates (8 for a 40M-follower profile) — it is a trap."""
    out = _flatten_linkedin(PROFILE)
    assert "Followers: 40,549,518" in out
    assert "Connections" not in out


def test_noise_keys_are_excluded():
    out = _flatten_linkedin(PROFILE)
    assert "Sundar" not in out
    assert "Top Voices" not in out


def test_icp_relevant_flags_surface():
    hiring = dict(PROFILE, hiring=True, openToWork=True)
    out = _flatten_linkedin(hiring)
    assert "hiring" in out
    assert "open to work" in out


def test_experience_and_education_render():
    out = _flatten_linkedin(PROFILE)
    assert "- Co-chair at Gates Foundation (26 yrs 7 mos)" in out
    assert "Education: Harvard University, Lakeside School" in out


def test_plain_handles_scalars_dicts_and_none():
    assert _plain("hello") == "hello"
    assert _plain(None) == ""
    assert _plain({"text": "abc"}) == "abc"
    assert _plain({"parsed": {"text": "nested"}}) == "nested"
    assert _plain({"unknown": "shape"}) == ""


def test_clean_markdown_drops_images_keeps_link_text():
    raw = (
        "# Our Services\n\n"
        "![Alt description not provided](https://cdn.example.com/a.jpg?w=810&h=528)\n\n"
        "We offer [fractional COO engagements](https://example.com/services/coo).\n\n\n\n"
        "[](https://example.com/empty)\n"
    )
    cleaned = _clean_markdown(raw)
    assert "cdn.example.com" not in cleaned
    assert "fractional COO engagements" in cleaned
    assert "https://example.com/services/coo" not in cleaned
    assert "\n\n\n" not in cleaned


# --- LinkedIn URL shape gating ------------------------------------------------

import asyncio

import pytest

from app.clients.apify import scrape_linkedin


def _scrape(url):
    return asyncio.run(scrape_linkedin(None, url))


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/company/kronos/",
        "https://linkedin.com/school/harvard/",
        "https://www.linkedin.com/showcase/microsoft-teams/",
    ],
)
def test_company_pages_are_rejected_before_spending_an_actor_run(url):
    """Leads paste company pages into the LinkedIn field constantly.

    Passing one to the profile actor burns a run and returns nothing, which read as
    'profile not found or private' — a misleading error that sends you debugging the
    wrong thing.
    """
    result = _scrape(url)
    assert not result.ok
    assert "company page" in result.error


def test_junk_urls_are_rejected():
    result = _scrape("https://example.com/about")
    assert not result.ok
    assert "not a recognisable" in result.error


def test_empty_url_is_not_an_error_state_worth_scraping():
    assert _scrape("").error == "no LinkedIn URL provided"
